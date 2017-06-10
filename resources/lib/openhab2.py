# coding=utf-8

import base64
import collections
try:    # OrderedDict is new in python 2.7
    from collections import OrderedDict as OrderedDict
except:
    from ordereddict import OrderedDict
import datetime
import time
import re
import requests
import threading
import weakref
from decimal import Decimal
from decimal import InvalidOperation
from debugout import debugPrint


def split_label(label):
    """Split a label + value line into label and value, e.g.
       "Outside Temperature [9,0 °C]"
       -> label = "Outside Temperature"
       -> value = "9,0 °C"
    """
    if label is None:
        return None, None

    m = re.search(r"\s*\[([^\]]*)\]$", label)
    if m is not None:
        return label[:m.start()], m.groups()[0]
    else:
        return label, None


def as_array(x):
    """openHAB doesn't return an array of objects in the JSON rest API if there is only 1 entry in
       the array. Therefore this functions converts single entries into an array."""
    if isinstance(x, list):
        return x
    else:
        return [x]


def convert_mapping(raw):
    """Convert openHAB mapping into a python ordered dictionary"""
    if raw is None:
        return None
    else:
        mapping = OrderedDict()
        for l in as_array(raw):
            try:
                mapping[Decimal(l['command'])] = l['label']
            except InvalidOperation:
                mapping[l['command']] = l['label']
        return mapping


def update_proxy(func):
    """Decorator function to update all assigned proxies if any attribute changes"""
    def func_wrapper(self, *args, **kwargs):
        func(self, *args, **kwargs)
        updates = self.attribs.get_changes()
        for p in self.proxies:
            ref = p()
            if ref:
                ref.update(*updates)

    return func_wrapper


class EmptyResponseError(Exception):
    """Exception for empty openHAB responses"""
    pass


def poll_page_thread(page):
    """Thread function to long-poll openHAB pages"""
    while True:
        try:
            page.get_page_blocked()
        except EmptyResponseError:
            # openHAB server return an empty reponse (typically 5 minutes after long-poll request started)
            # ==> try again if server connection is still alive
            debugPrint(5, 'poll_page_thread: empty response for page %s' % page.id_)
        except requests.exceptions.ReadTimeout as e:
            # HTTP request timed out
            # ==> try again if server connection is still alive
            debugPrint(5, 'poll_page_thread: %s for page %s' % (repr(e), page.id_))
        except requests.exceptions.HTTPError as e:
            debugPrint(1, 'poll_page_thread: %s for page %s' % (repr(e), page.id_))
        except requests.exceptions.ConnectTimeout as e:
            debugPrint(1, 'poll_page_thread: %s for page %s' % (repr(e), page.id_))
        except requests.exceptions.ConnectionError as e:
            # openHAB server terminated the connection
            # ==> execute terminate callback and close window
            debugPrint(5, 'poll_page_thread: %s for page %s' % (repr(e), page.id_))
            page.oh.terminate()

        if not page.oh.alive:
            # exit thread if openHAB server ist not alive any more"""
            return


class Attributes(collections.MutableMapping):
    """A dictionary that tracks changes and stores new/changed key/value + deleted keys"""

    def __init__(self, prefix, *args, **kwargs):
        self.prefix = prefix
        self.changed = dict()  # stores new and changed key/values
        self.deleted = set()  # stores deleted keys
        self.store = dict()
        self.update(dict(*args, **kwargs))  # use the free update to set keys

    def __getitem__(self, key):
        return self.store[key]

    def __setitem__(self, key, value):
        try:
            if self.store[key] == value:
                return  # skip further processing because value unchanged
        except KeyError:
            pass

        self.store[key] = value

        xkey = self.prefix + key
        self.changed[xkey] = value
        try:
            self.deleted.remove(xkey)
        except KeyError:
            pass

    def __delitem__(self, key):
        del self.store[key]

        xkey = self.prefix + key
        self.deleted.add(xkey)
        try:
            del self.changed[xkey]
        except KeyError:
            pass

    def __iter__(self):
        return iter(self.store)

    def __len__(self):
        return len(self.store)

    def get_changes(self):
        result = (self.changed, self.deleted)
        self.changed = dict()
        self.deleted = set()
        return result

    def get_all(self):
        changed = dict()
        for key, value in self.store.iteritems():
            changed[self.prefix + key] = value
        return changed


class Server(object):
    """Python representative of a running openHAB instance."""
    def __init__(self, host='localhost', port='8080'):
        self.host = host
        self.port = port
        path = 'http://%s:%s/' % (host, port)
        self.resources = {'items': path + 'rest/items',
                          'sitemaps': path + 'rest/sitemaps',
                          'images': path + 'images',
                          'charts': path + 'chart'}
        self.sitemaps = {}
        self.pages = {}
        self.items = {}
        self.widgets = {}
        self.http_put_headers = {'content-type': 'text/plain'}
        self.http_get_headers = {'accept': 'application/json'}
        self.poll_pages = False     # True = start thread for every new page to long-poll changes
        self.http_proxies = None      # proxy for requests library
        self.alive = True
        self.terminate_callback = []

    def terminate(self):
        self.alive = False
        for cb in self.terminate_callback:
            cb(self)

    def set_basic_auth(self, username, password):
        auth = 'Basic %s' % base64.b64encode('%s:%s' % (username, password))
        self.http_put_headers['authorization'] = auth
        self.http_get_headers['authorization'] = auth

    def set_proxy(self, proxy):
        if proxy == 'system':
            self.http_proxies = None     # use system proxies
        elif proxy == 'none':
            self.http_proxies = {'http': '', 'https': ''}     # use no proxy
        else:
            self.http_proxies = {'http': proxy, 'https': proxy}

    def fetch_abs_json_url(self, url, extra_headers=None):
        """Fetch url from openHAB  server and convert data from json to Python data structures."""
        headers = self.http_get_headers
        if extra_headers is not None:
            headers.update(extra_headers)
        debugPrint(5, 'fetching json url=%s, headers=%s' % (url, repr(headers)))
        resp = requests.get(url, headers=headers, proxies=self.http_proxies)
        debugPrint(5, 'response for url=%s, text=%s, headers=%s' % (url, resp.text, resp.headers))
        if resp.status_code != requests.codes.ok:
            resp.raise_for_status()
        if resp.text == '':
            # openHAB returns an empty response after 5 minutes if long-polling is enabled
            raise EmptyResponseError
        return resp.json(), resp.headers

    def fetch_rel_json_url(self, name, headers=None):
        """Fetch url from openHAB server and convert data from json to Python data structures."""
        return self.fetch_abs_json_url('http://%s:%s/rest%s' % (self.host, self.port, name), headers)

    def load_resources(self):
        """Fetch resources (http:<ip>:<port>/rest) from openHAB."""
        self.resources = {}
        result = self.fetch_rel_json_url('', self.http_get_headers)[0]
        for item in as_array(result['link']):
            self.resources[item['@type']] = item['$']
        return self.resources

    def load_sitemaps(self):
        """Load sitemaps list from openHAB and create Python instances for every sitemap. 
           The created sitemaps are without content so far."""
        self.sitemaps = {}
        if not self.resources:
            self.load_resources()
        result = self.fetch_abs_json_url(self.resources['sitemaps'])[0]
        for i in as_array(result):
            self.sitemaps[i['name']] = Sitemap(self, i)
        return self.sitemaps

    def load_items(self):
        """Load items from openHAB and create python instances for every openHAB item."""
        self.items = {}
        if not self.resources:
            self.load_resources()
        result = self.fetch_abs_json_url(self.resources['items'])[0]
        for itemData in as_array(result['item']):
            self.create_item_class(itemData)
        return self.items

    def create_page_class(self, sitemap, pageData, prevPage=None):
        """Create an openHAB page instance from the given hash properties."""
        if pageData is None:
            return None
        elif pageData['id'] in self.pages:      # test if page already exists
            i = self.pages[pageData['id']]
            i.init(pageData)
            return i
        else:
            i = Page(sitemap, pageData, prevPage)

            if self.poll_pages:
                # start a new thread for every page that polls updates
                t = threading.Thread(target=poll_page_thread, args=(i,))
                t.daemon = True
                t.start()

            # add new instance to dict of all pages
            self.pages[i.id_] = i
            return i

    def create_item_class(self, itemData):
        """Create an openHAB item instance from the given hash properties."""
        if itemData is None:
            return None
        elif itemData['name'] in self.items:    # test if item already exists
            i = self.items[itemData['name']]
            i.init(itemData)
            return i
        else:
            if itemData['type'] == 'Call':
                i = CallItem(self, itemData)
            elif itemData['type'] == 'Color':
                i = ColorItem(self, itemData)
            elif itemData['type'] == 'Contact':
                i = ContactItem(self, itemData)
            elif itemData['type'] == 'DateTime':
                i = DateTimeItem(self, itemData)
            elif itemData['type'] == 'Dimmer':
                i = DimmerItem(self, itemData)
            elif itemData['type'] == 'Group':
                i = GroupItem(self, itemData)
            elif itemData['type'] == 'Location':
                i = LocationItem(self, itemData)
            elif itemData['type'] == 'Number':
                i = NumberItem(self, itemData)
            elif itemData['type'] == 'String':
                i = StringItem(self, itemData)
            elif itemData['type'] == 'Switch':
                i = SwitchItem(self, itemData)
            elif itemData['type'] == 'Rollershutter':
                i = RollerShutterItem(self, itemData)
            else:
                debugPrint(1, 'unknown item type=%s, name=%s' % (itemData['type'], itemData['name']))
                return None

            # add new instance to dict of all items
            self.items[i.name] = i
            return i

    def create_widget_class(self, page, widgetData):
        """ create an openHAB widget instance from the given has properties """
        if widgetData is None:
            return None
        elif widgetData['widgetId'] in self.widgets:  # test if widget already exists
            i = self.widgets[widgetData['widgetId']]
            i.init(widgetData)
            return i
        else:
            if widgetData['type'] == 'Colorpicker':
                i = ColorPickerWidget(page, widgetData)
            elif widgetData['type'] == 'Chart':
                i = ChartWidget(page, widgetData)
            elif widgetData['type'] == 'Frame':
                i = FrameWidget(page, widgetData)
            elif widgetData['type'] == 'Group':
                i = GroupWidget(page, widgetData)
            elif widgetData['type'] == 'Image':
                i = ImageWidget(page, widgetData)
            elif widgetData['type'] == 'Selection':
                i = SelectionWidget(page, widgetData)
            elif widgetData['type'] == 'Setpoint':
                i = SetPointWidget(page, widgetData)
            elif widgetData['type'] == 'Slider':
                i = SliderWidget(page, widgetData)
            elif widgetData['type'] == 'Switch':
                i = SwitchWidget(page, widgetData)
            elif widgetData['type'] == 'Text':
                i = TextWidget(page, widgetData)
            elif widgetData['type'] == 'Video':
                i = VideoWidget(page, widgetData)
            elif widgetData['type'] == 'Mapview':
                i = MapViewWidget(page, widgetData)
            elif widgetData['type'] == 'Webview':
                i = WebViewWidget(page, widgetData)
            else:
                debugPrint(1, 'unknown widget type=%s, widgetId=%s' % (widgetData['type'], widgetData['widgetId']))
                return None

            # add new instance to dict of all widgets
            self.widgets[i.widgetId] = i
            return i


class Sitemap(object):
    """Python representative of an openHAB sitemap."""

    def __init__(self, oh, sitemapData):
        self.oh = oh
        self.name = sitemapData['name']
        self.label = sitemapData['label']
        self.link = sitemapData['link']
        self.page = None

    def load_page(self):
        """Load sitemap homepage from openHAB and create SitemapPage instance."""
        result = self.oh.fetch_abs_json_url(self.link)[0]
        self.page = self.oh.create_page_class(self, result['homepage'])
        return self.page


class Page(object):
    """Python representative of a page of widgets in openHAB. A page can be the homepage of a sitemap
       or the linked page of a group or text widget."""

    def __init__(self, sitemap, pageData, prevPage=None):
        self.sitemap = sitemap
        self.prevPage = prevPage
        self.oh = sitemap.oh
        self.id_ = pageData['id']
        self.attribs = Attributes('page_')
        self.proxies = []
        self.widgets = []
        self.atmos_id = None
        self.init(pageData)

    def set_proxy(self, proxy):
        self.proxies.append(weakref.ref(proxy))
        changed = self.attribs.get_all()
        proxy.update(changed, set())

    @update_proxy
    def init(self, pageData):
        self.attribs['link'] = pageData['link']
        self.attribs['leaf'] = pageData['leaf']
        x = split_label(pageData.get('title'))
        self.attribs['title'] = x[0]
        self.attribs['value'] = x[1]
        if 'widgets' in pageData:
            self.create_all_widgets(as_array(pageData['widgets']))

    def create_all_widgets(self, widgets):
        # create list of all existing widget-ids in case of an update
        id_list = frozenset([w.widgetId for w in self.widgets])
        for w in widgets:
            i = self.oh.create_widget_class(self, w)
            if i is not None and i.widgetId not in id_list:
                self.widgets.append(i)

    def get_page(self, headers=None):
        (pageData, headers) = self.oh.fetch_abs_json_url(self.attribs['link'], headers)
        self.init(pageData)
        self.atmos_id = headers.get('x-atmosphere-tracking-id')

    def get_page_blocked(self):
        headers = {'x-atmosphere-transport': 'long-polling'}
        if self.atmos_id is not None:
            headers['x-atmosphere-tracking-id'] = self.atmos_id
        self.get_page(headers)


class WidgetBase(object):
    def __init__(self, page, widgetData):
        self.page = page
        self.oh = page.oh
        self.type_ = widgetData['type']
        self.widgetId = widgetData['widgetId']
        self.item = None
        self.attribs = Attributes('widget_')
        self.proxies = []
        self.init(widgetData)

    @update_proxy
    def init(self, widgetData):
        x = split_label(widgetData.get('label'))
        self.attribs['label'] = x[0]
        self.attribs['value'] = x[1]
        if 'icon' in widgetData and widgetData['icon'] != 'none':
            self.attribs['icon'] = self.oh.resources['images'] + '/' + widgetData['icon'] + '.png'
        else:
            self.attribs['icon'] = None
        self.attribs['label_color'] = widgetData.get('labelcolor')
        self.attribs['value_color'] = widgetData.get('valuecolor')
        self.item = self.oh.create_item_class(widgetData.get('item'))

    def set_proxy(self, proxy):
        self.proxies.append(weakref.ref(proxy))
        proxy.update(self.attribs.get_all(), set())

        if self.item:
            self.item.set_proxy(proxy)


class ColorPickerWidget(WidgetBase):
    def __init__(self, page, widgetData):
        super(ColorPickerWidget, self).__init__(page, widgetData)


class ChartWidget(WidgetBase):
    def __init__(self, page, widgetData):
        super(ChartWidget, self).__init__(page, widgetData)

    @update_proxy
    def init(self, widgetData):
        super(ChartWidget, self).init(widgetData)
        self.attribs['service'] = widgetData.get('service')
        self.attribs['period'] = widgetData.get('period')
        self.attribs['refresh'] = int(widgetData.get('refresh', 0))
        url = self.oh.resources['charts'] + '?'
        if self.item.type_ == 'GroupItem':
            url += 'groups=' + self.item.name
        if 'period' in self.attribs:
            url += '&period=' + self.attribs['period']
        self.attribs['url'] = url


class FrameWidget(WidgetBase):
    def __init__(self, page, widgetData):
        self.widgets = []  # assign widgets before calling super because this in turns calls init
        super(FrameWidget, self).__init__(page, widgetData)

    @update_proxy
    def init(self, widgetData):
        super(FrameWidget, self).init(widgetData)
        if 'widgets' in widgetData:
            self.widgets = []
            for w in as_array(widgetData['widgets']):
                i = self.oh.create_widget_class(self.page, w)
                if i is not None:
                    self.widgets.append(i)


class GroupWidget(WidgetBase):
    def __init__(self, page, widgetData):
        super(GroupWidget, self).__init__(page, widgetData)

    @update_proxy
    def init(self, widgetData):
        super(GroupWidget, self).init(widgetData)
        if 'linkedPage' in widgetData:
            self.page = self.oh.create_page_class(self.page.sitemap, widgetData['linkedPage'], self.page)
        else:
            self.page = None



class ImageWidget(WidgetBase):
    def __init__(self, page, widgetData):
        super(ImageWidget, self).__init__(page, widgetData)

    @update_proxy
    def init(self, widgetData):
        super(ImageWidget, self).init(widgetData)
        self.attribs['linkedPage'] = widgetData['linkedPage']  # don't create an extra Page because not used so far
        self.attribs['url'] = widgetData['url']
        self.attribs['refresh'] = int(widgetData.get('refresh', 0))


class SelectionWidget(WidgetBase):
    def __init__(self, page, widgetData):
        super(SelectionWidget, self).__init__(page, widgetData)

    @update_proxy
    def init(self, widgetData):
        super(SelectionWidget, self).init(widgetData)
        self.attribs['mapping'] = convert_mapping(widgetData.get('mappings'))
        if self.attribs['mapping'] and self.attribs['value'] is None and self.item.attribs['state'] is not None:
            self.attribs['value'] = self.attribs['mapping'].get(self.item.attribs['state'])


class SetPointWidget(WidgetBase):
    def __init__(self, page, widgetData):
        super(SetPointWidget, self).__init__(page, widgetData)

    @update_proxy
    def init(self, widgetData):
        super(SetPointWidget, self).init(widgetData)
        self.attribs['min_value'] = Decimal(widgetData['minValue'])
        self.attribs['max_value'] = Decimal(widgetData['maxValue'])
        self.attribs['step'] = Decimal(widgetData['step'])


class SliderWidget(WidgetBase):
    def __init__(self, page, widgetData):
        super(SliderWidget, self).__init__(page, widgetData)

    @update_proxy
    def init(self, widgetData):
        super(SliderWidget, self).init(widgetData)
        self.attribs['min_value'] = Decimal(0)
        self.attribs['max_value'] = Decimal(100)
        self.attribs['step'] = Decimal(1)
        self.attribs['send_frequency'] = int(widgetData.get('sendFrequency', 0))
        self.attribs['switch_support'] = widgetData.get('switchSupport', False)


class SwitchWidget(WidgetBase):
    def __init__(self, page, widgetData):
        super(SwitchWidget, self).__init__(page, widgetData)

    @update_proxy
    def init(self, widgetData):
        super(SwitchWidget, self).init(widgetData)
        self.attribs['mapping'] = convert_mapping(widgetData.get('mappings'))
        if self.attribs['mapping'] and self.attribs['value'] is None and self.item.attribs['state'] is not None:
            self.attribs['value'] = self.attribs['mapping'].get(self.item.attribs['state'])


class TextWidget(WidgetBase):
    def __init__(self, page, widgetData):
        super(TextWidget, self).__init__(page, widgetData)

    @update_proxy
    def init(self, widgetData):
        super(TextWidget, self).init(widgetData)
        if 'linkedPage' in widgetData:
            self.page = self.oh.create_page_class(self.page.sitemap, widgetData['linkedPage'], self.page)
        else:
            self.page = None


class VideoWidget(WidgetBase):
    def __init__(self, page, widgetData):
        super(VideoWidget, self).__init__(page, widgetData)

    @update_proxy
    def init(self, widgetData):
        super(VideoWidget, self).init(widgetData)
        self.attribs['url'] = widgetData['url']
        self.attribs['encoding'] = widgetData.get('encoding')


class MapViewWidget(WidgetBase):
    def __init__(self, page, widgetData):
        super(MapViewWidget, self).__init__(page, widgetData)

    @update_proxy
    def init(self, widgetData):
        super(MapViewWidget, self).init(widgetData)


class WebViewWidget(WidgetBase):
    def __init__(self, page, widgetData):
        super(WebViewWidget, self).__init__(page, widgetData)

    @update_proxy
    def init(self, widgetData):
        super(WebViewWidget, self).init(widgetData)
        self.attribs['height'] = int(widgetData.get('height', 1))
        self.attribs['url'] = widgetData['url']


class ItemBase(object):
    def __init__(self, oh, itemData):
        self.oh = oh
        self.name = itemData['name']
        self.type_ = itemData['type']
        self.link = itemData['link']
        self.attribs = Attributes('item_')
        self.proxies = []
        self.atmos_id = None  # ID used for long polling
        self.init(itemData)

    def set_proxy(self, proxy):
        self.proxies.append(weakref.ref(proxy))
        proxy.update(self.attribs.get_all(), set())

    @update_proxy
    def init(self, itemData):
        self.attribs['state'] = self.state_from_string(itemData['state']) if 'state' in itemData else None

    def state_from_string(self, value):
        raise RuntimeError()

    def state_to_string(self, value):
        raise RuntimeError()

    def test_state_value(self, value):
        raise RuntimeError()

    @update_proxy
    def set_state(self, value):
        new_state = self.test_state_value(value)
        if self.attribs['state'] != new_state:
            self.attribs['state'] = new_state
            self.post_state()  # send update to openHAB

    def send_command(self, value):
        """ post command to openHAB, used for actor items """
        resp = requests.post(self.link, data=value, headers=self.oh.http_put_headers, proxies=self.oh.http_proxies)
        if resp.status_code != requests.codes.ok:
            resp.raise_for_status()

    def post_state(self):
        """ post state update to openHAB, used for sensor items """
        resp = requests.put(self.link + '/state', data=self.state_to_string(self.attribs['state']),
                            headers=self.oh.http_put_headers, proxies=self.oh.http_proxies)
        if resp.status_code != requests.codes.ok:
            resp.raise_for_status()

    def get_state(self, headers=None):
        (result, headers) = self.oh.fetch_abs_json_url(self.link, headers)
        if 'state' in result:
            self.init(result)
        self.atmos_id = headers.get('x-atmosphere-tracking-id')

    def get_state_blocked(self):
        headers = {'x-atmosphere-transport': 'long-polling'}
        if self.atmos_id is not None:
            headers['x-atmosphere-tracking-id'] = self.atmos_id
        self.get_state(headers)


class CallItem(ItemBase):
    def __init__(self, oh, itemData):
        super(CallItem, self).__init__(oh, itemData)

    def state_from_string(self, value):
        if value is None or value in ('NULL', 'UNDEF'):
            return None
        else:
            return value

    def state_to_string(self, value):
        if value is None:
            return 'UNDEF'
        else:
            return value

    def test_state_value(self, value):
        if not isinstance(value, str):
            raise TypeError()
        return value

    def cmd_call(self, value):
        if not isinstance(value, str):
            raise TypeError()
        self.send_command(value)


class ColorItem(ItemBase):
    def __init__(self, oh, itemData):
        super(ColorItem, self).__init__(oh, itemData)

    def state_from_string(self, value):
        if value is None or value in ('NULL', 'UNDEF'):
            return None
        else:
            return map(lambda x: float(x), value.split(',', 3))

    def state_to_string(self, value):
        if value is None:
            return 'UNDEF'
        else:
            return ','.join(map(lambda x: str(x), value))

    def test_state_value(self, value):
        if not isinstance(value, collections.Sequence):
            raise TypeError()
        return value

    def cmd_on(self):
        self.send_command('ON')

    def cmd_off(self):
        self.send_command('OFF')

    def cmd_increase(self):
        self.send_command('INCREASE')

    def cmd_decrease(self):
        self.send_command('DECREASE')

    @update_proxy
    def cmd_set_pct(self, value):
        if not isinstance(value, (int, float, Decimal)):
            raise TypeError()
        self.send_command(str(value))
        #self.attribs['state'] = value

    @update_proxy
    def cmd_set_hsv(self, value):
        if not isinstance(value, collections.Sequence):
            raise TypeError()
        self.send_command(','.join(map(lambda x: str(x), value)))
        #self.attribs['state'] = value


class ContactItem(ItemBase):
    def __init__(self, oh, itemData):
        super(ContactItem, self).__init__(oh, itemData)

    def state_from_string(self, value):
        if value is None or value in ('NULL', 'UNDEF'):
            return None
        elif value == 'open':
            return True
        elif value == 'closed':
            return False
        else:
            raise ValueError()

    def state_to_string(self, value):
        if value is None:
            return 'UNDEF'
        elif value:
            return 'open'
        else:
            return 'closed'

    def test_state_value(self, value):
        if not isinstance(value, bool):
            raise TypeError()
        return value


class DateTimeItem(ItemBase):
    def __init__(self, oh, itemData):
        super(DateTimeItem, self).__init__(oh, itemData)

    def state_from_string(self, value):
        if value is None or value in ('NULL', 'UNDEF'):
            return None
        else:
            # datetime.strptime is not available on Kodi, therefore this workaround
            # see also: http://forum.kodi.tv/showthread.php?tid=112916
            value = value.partition('.')[0] # remove ms and UTC offset because also not supported
            t = time.strptime(value, '%Y-%m-%dT%H:%M:%S')
            return datetime.datetime.fromtimestamp(time.mktime(t))

    def state_to_string(self, value):
        if value is None:
            return 'UNDEF'
        else:
            return value.isoformat()

    def test_state_value(self, value):
        if not isinstance(value, datetime.datetime):
            raise TypeError()
        return value


class DimmerItem(ItemBase):
    def __init__(self, oh, itemData):
        super(DimmerItem, self).__init__(oh, itemData)

    def state_from_string(self, value):
        if value is None or value in ('NULL', 'UNDEF'):
            return None
        else:
            return Decimal(value)

    def state_to_string(self, value):
        if value is None:
            return 'UNDEF'
        else:
            return str(value)

    def test_state_value(self, value):
        if not isinstance(value, (int, float, Decimal)):
            raise TypeError()
        return value

    @update_proxy
    def cmd_set(self, value):
        if not isinstance(value, (int, float, Decimal)):
            raise TypeError()
        self.send_command(str(value))
        self.attribs['state'] = value

    def cmd_on(self):
        self.send_command('ON')

    def cmd_off(self):
        self.send_command('OFF')

    def cmd_increase(self):
        self.send_command('INCREASE')

    def cmd_decrease(self):
        self.send_command('DECREASE')

    def cmd_toggle(self):
        self.send_command('TOGGLE')


class GroupItem(ItemBase):
    def __init__(self, oh, itemData):
        super(GroupItem, self).__init__(oh, itemData)

    def state_from_string(self, value):
        if value is None or value in ('NULL', 'UNDEF'):
            return None
        else:
            return value

    def cmd_set(self, value):
        self.send_command(str(value))


class LocationItem(ItemBase):
    def __init__(self, oh, itemData):
        super(LocationItem, self).__init__(oh, itemData)

    def state_from_string(self, value):
        if value is None or value in ('NULL', 'UNDEF'):
            return None
        else:
            return value

    def state_to_string(self, value):
        if value is None:
            return 'UNDEF'
        else:
            return value

    def test_state_value(self, value):
        if not isinstance(value, str):
            raise TypeError()
        return value


class NumberItem(ItemBase):
    def __init__(self, oh, itemData):
        super(NumberItem, self).__init__(oh, itemData)

    def state_from_string(self, value):
        if value is None or value in ('NULL', 'UNDEF'):
            return None
        else:
            return Decimal(value)

    def state_to_string(self, value):
        if value is None:
            return 'UNDEF'
        else:
            return str(value)

    def test_state_value(self, value):
        if not isinstance(value, (int, float, Decimal)):
            raise TypeError()
        return value

    @update_proxy
    def cmd_set(self, value):
        if not isinstance(value, (int, float, Decimal)):
            raise TypeError()
        self.send_command(str(value))
        self.attribs['state'] = value


class RollerShutterItem(ItemBase):
    def __init__(self, oh, itemData):
        super(RollerShutterItem, self).__init__(oh, itemData)

    def state_from_string(self, value):
        if value is None or value in ('NULL', 'UNDEF'):
            return None
        else:
            return Decimal(value)

    def state_to_string(self, value):
        if value is None:
            return 'UNDEF'
        #        elif isinstance(value, str):
        #            return value
        else:
            return str(value)

    def test_state_value(self, value):
        # if value not in ('UP', 'DOWN') and not isinstance(value, (int, float)):
        if not isinstance(value, (int, float, Decimal)):
            raise TypeError()
        return value

    @update_proxy
    def cmd_set(self, value):
        if not isinstance(value, (int, float, Decimal)):
            raise TypeError()
        self.send_command(str(value))
        self.attribs['state'] = value

    def cmd_stop(self):
        self.send_command('STOP')

    def cmd_move(self):
        self.send_command('MOVE')

    def cmd_up(self):
        self.send_command('UP')

    def cmd_down(self):
        self.send_command('DOWN')

    def cmd_toggle(self):
        self.send_command('TOGGLE')


class StringItem(ItemBase):
    def __init__(self, oh, itemData):
        super(StringItem, self).__init__(oh, itemData)

    def state_from_string(self, value):
        if value is None or value in ('NULL', 'UNDEF'):  # REVISIT: what is the string for an uninitialized string item?
            return None
        else:
            return value

    def state_to_string(self, value):
        if value is None:
            return 'UNDEF'  # REVISIT: what is the string for an undefined string item?
        else:
            return value

    def test_state_value(self, value):
        if not isinstance(value, str):
            raise TypeError()
        return value

    @update_proxy
    def cmd_set(self, value):
        if not isinstance(value, str):
            raise TypeError()
        self.send_command(value)
        self.attribs['state'] = value


class SwitchItem(ItemBase):
    def __init__(self, oh, itemData):
        super(SwitchItem, self).__init__(oh, itemData)

    def state_from_string(self, value):
        if value is None or value in ('NULL', 'UNDEF'):
            return None
        elif value == 'ON':
            return True
        elif value == 'OFF':
            return False
        else:
            return None #raise ValueError

    def state_to_string(self, value):
        if value is None:
            return 'UNDEF'
        elif value:
            return 'ON'
        else:
            return 'OFF'

    def test_state_value(self, value):
        if not isinstance(value, bool):
            raise TypeError()
        return value

    @update_proxy
    def cmd_set(self, value):
        if not isinstance(value, bool):
            raise TypeError()
        self.send_command(self.state_to_string(value))
        self.attribs['state'] = value

    @update_proxy
    def cmd_on(self):
        self.send_command('ON')
        self.attribs['state'] = True

    @update_proxy
    def cmd_off(self):
        self.send_command('OFF')
        self.attribs['state'] = False

    @update_proxy
    def cmd_toggle(self):
        self.send_command('TOGGLE')
        self.attribs['state'] = not self.attribs['state']


if __name__ == '__main__':
    oh = Server('localhost')
    oh.poll_pages = True
    oh.load_sitemaps()
    homepage = oh.sitemaps['demo'].load_page()