# coding=utf-8

import xbmc
import xbmcaddon
import xbmcgui
import sys
import requests
import resources.lib.menulist as menulist
import resources.lib.openhab1 as openhab1
import resources.lib.openhab2 as openhab2
from resources.lib.debugout import debugPrint

ADDON = xbmcaddon.Addon()


def getServer():
    if ADDON.getSetting('server') == '0':  # openhab1
        return openhab1
    elif ADDON.getSetting('server') == '1':  # openhab2
        return openhab2


class MainWindow(menulist.MainWindow):
    class WindowStackEntry(object):
        def __init__(self, widgets, title, position=None):
            self.widgets = widgets
            self.title = title
            self.position = position

    def __init__(self):
        super(MainWindow, self).__init__()
        self.windowStack = []
        self.oh = None
        self.homepage = None

    def build_menu(self):
        self.oh = getServer().Server(ADDON.getSetting('host'), ADDON.getSetting('port'))
        self.oh.terminate_callback.append(lambda oh: self.connection_lost())

        #if ADDON.getSetting('auto_update') == 'true':
        self.oh.poll_pages = True       # always enable auto-update

        if ADDON.getSetting('authentication') == '1':
            self.oh.set_basic_auth(ADDON.getSetting('auth_basic_username'), ADDON.getSetting('auth_basic_password'))

        PROXY_MAP = {'0': 'system', '1': 'none'}
        self.oh.set_proxy(PROXY_MAP[ADDON.getSetting('proxy')])

        try:
            self.oh.load_sitemaps()
            try:
                sitemap = self.oh.sitemaps[ADDON.getSetting('sitemap')]
            except KeyError:
                # invalid sitemap -> close window immediately
                debugPrint(1, "build_menu failed, host=%s, port=%s, auth=%s, sitemap=%s sitemaps=%s" %
                       (ADDON.getSetting('host'), ADDON.getSetting('port'),
                        ADDON.getSetting('authentication'), ADDON.getSetting('sitemap'), self.oh.sitemaps))
                xbmcgui.Dialog().ok(ADDON.getLocalizedString(30007), ADDON.getLocalizedString(30206))
                self.close()
                ADDON.openSettings()
            self.homepage = sitemap.load_page()
        except requests.exceptions.RequestException as e:
            # no connection to openhab server -> close window immediately
            debugPrint(1, "build_menu failed, host=%s, port=%s, auth=%s, e=%s" %
                   (ADDON.getSetting('host'), ADDON.getSetting('port'),
                    ADDON.getSetting('authentication'), repr(e)))
            xbmcgui.Dialog().ok(ADDON.getLocalizedString(30007), ADDON.getLocalizedString(30201))
            self.close()
            ADDON.openSettings()
        self.enter_sub_menu(self.homepage)

    def enter_sub_menu(self, page):
        # store current focus position
        if self.windowStack:
            self.windowStack[-1].position = self.list.get_selected_position()
        # add new page to stack
        self.windowStack.append(self.WindowStackEntry(page.widgets, page.attribs['title'], None))
        # open last entry on stack
        self.load_widgets_from_stack()

    def load_widgets_from_stack(self):
        # get last entry on window stack
        e = self.windowStack[-1]
        # clear list control
        self.list.reset()
        # load all widgets
        self.load_widgets(e.widgets)
        # recover last focus position before opening submenu
        if e.position is not None:
            self.list.select_item(e.position)
        else:
            self.list.select_first_item()
        # set breadcrumb as title
        self.setProperty('title', ' > '.join([x.title for x in self.windowStack]))

    def load_widgets(self, widgets):
        for w in widgets:
            li = None
            subordinate_widgets = None
            if w.type_ == 'Colorpicker':
                li = menulist.ListItemColor(w.item)
            elif w.type_ == 'Chart':
                li = menulist.ListItemLabel()
                li.subscribe(lambda control, url=w.attribs['url']: self.show_image(url))
                li.set_show_next_icon(True)
            elif w.type_ == 'Frame':
                if w.attribs['label']:
                    li = menulist.ListItemSeparator()
                subordinate_widgets = w.widgets
            elif w.type_ == 'Group':
                li = menulist.ListItemText()
                if w.page is not None:
                    li.subscribe(lambda control, page=w.page: self.enter_sub_menu(page))
                    li.set_show_next_icon(True)
            elif w.type_ == 'Image':
                li = menulist.ListItemLabel()
                li.subscribe(lambda control, url=w.attribs['url']: self.show_image(url))
                li.set_show_next_icon(True)
            elif w.type_ == 'Selection':
                li = menulist.ListItemSelection(w.item)
            elif w.type_ == 'Setpoint':
                li = menulist.ListItemSetPoint(w.item)
            elif w.type_ == 'Slider':
                li = menulist.ListItemSlider(w.item)
            elif w.type_ == 'Switch':
                item_type = w.item.type_

                if item_type.endswith('Item'):  # remove trailing 'Item' from openhab1
                    item_type = item_type[:-4]

                if item_type == 'Switch':
                    li = menulist.ListItemSwitch(w.item)
                elif item_type == 'Rollershutter':
                    li = menulist.ListItemRollerShutter(w.item)
                elif item_type == 'Number':
                    li = menulist.ListItemSelection(w.item)
                elif item_type == 'Group':
                    li = menulist.ListItemSelection(w.item)
                else:
                    debugPrint(1, 'SwitchWidget [%s]: unsupported item type: %s' % (w.widgetId, w.item.type_))
            elif w.type_ == 'Text':
                li = menulist.ListItemText()
                if w.page is not None:
                    li.subscribe(lambda control, page=w.page: self.enter_sub_menu(page))
                    li.set_show_next_icon(True)
            elif w.type_ == 'Video':
                li = menulist.ListItemLabel()
                li.subscribe(lambda control, url=w.attribs['url']: self.show_video(url))
                li.set_show_next_icon(True)
            elif w.type_ == 'Mapview':
                li = menulist.ListItemLabel()
            elif w.type_ == 'Webview':
                li = menulist.ListItemLabel()
            else:
                debugPrint(1, 'unknown widget type=%s, widgetId=%s' % (w.type_, w.widgetId))
                continue

            if li is not None:
                self.list.add_item(li)
                w.set_proxy(li)
            else:
                self.list.add_separator_line_to_last_item()

            if subordinate_widgets:
                self.load_widgets(subordinate_widgets)

    def go_back(self):
        if len(self.windowStack) <= 1:
            # no more widgets on the stack => close the window
            self.oh.alive = False
            self.close()
        else:
            self.windowStack.pop()
            self.load_widgets_from_stack()

    def connection_lost(self):
        xbmcgui.Dialog().notification(ADDON.getLocalizedString(30007),
                                      ADDON.getLocalizedString(30205),
                                      xbmcgui.NOTIFICATION_WARNING)
        self.close()

    def show_image(self, url):
        self.close()
        xbmc.executebuiltin('ShowPicture(%s)' % url)

    def show_video(self, url):
        self.close()
        xbmc.Player().play(url)


def show_sitemaps():
    # show sitemap selection dialog instead of main window if called from settings dialog
    oh = getServer().Server(ADDON.getSetting('host'), ADDON.getSetting('port'))
    if ADDON.getSetting('authentication') == '1':
        oh.set_basic_auth(ADDON.getSetting('auth_basic_username'), ADDON.getSetting('auth_basic_password'))

    PROXY_MAP = {'0': 'system', '1': 'none'}
    oh.set_proxy(PROXY_MAP[ADDON.getSetting('proxy')])

    try:
        sitemaps = sorted(oh.load_sitemaps().iterkeys())
    except requests.exceptions.RequestException as e:
        debugPrint(1, "show_sitemaps failed, host=%s, port=%s, auth=%s, e=%s" %
                   (ADDON.getSetting('host'), ADDON.getSetting('port'),
                    ADDON.getSetting('authentication'), repr(e)))
        xbmcgui.Dialog().ok(ADDON.getLocalizedString(30007), ADDON.getLocalizedString(30008))
        return

    value = xbmcgui.Dialog().select(ADDON.getLocalizedString(30006), sitemaps)
    if value >= 0:
        ADDON.setSetting('sitemap', sitemaps[value])


if 'show_sitemaps' in sys.argv:
    show_sitemaps()
else:
    mw = MainWindow()
    mw.doModal()
    del mw
