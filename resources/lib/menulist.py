# coding=utf-8

import xbmcaddon
import xbmcgui
import weakref
from selectdialog import SelectDialog
from colorpicker import ColorPicker
from colorutils import hsv_degree_to_rgb_hex_str, rgb_hex_str_to_hsv_degree
from htmlcolors import HTML_COLORS
from debugout import debugPrint

ADDON = xbmcaddon.Addon()

# menulist.xml control ID's
CONTROL_ID_LIST = 1100

# xbmcgui action codes to go up/back in a window
WINDOW_EXIT_CODES = frozenset([xbmcgui.ACTION_PARENT_DIR,
                               xbmcgui.ACTION_PREVIOUS_MENU,
                               xbmcgui.ACTION_NAV_BACK,
                               xbmcgui.KEY_BUTTON_BACK])

# xbmcgui action codes for movements within a control list
FOCUS_CHANGED_CODES = {xbmcgui.ACTION_MOVE_RIGHT: 1,
                       xbmcgui.ACTION_MOVE_UP: -1,
                       xbmcgui.ACTION_MOVE_DOWN: 1}


# range function with Decimal (and float) support
def drange(start, stop, step):
    r = start
    while r <= stop:
        yield r
        r += step


def get_item_index(array, element):
        try:
            return array.index(element)
        except ValueError:
            return None


def get_color_string(label, color):
    if color is None:
        return label

    if color[0] == '#':
        color = color[1:]
    elif color.lower() == 'lightgray':
        return label    # lightgray is typically the default color
    else:       # use HTML colors
        try:
            color = HTML_COLORS[color.lower()][1:]
        except KeyError:
            return label

    return '[COLOR FF%s]%s[/COLOR]' % (color, label)


class ListItem(object):
    def __init__(self, typ, proxy):
        self.control = xbmcgui.ListItem()
        self.control.setProperty(u"type", typ)
        self.attribs = dict()
        self.proxy = weakref.ref(proxy) if proxy else lambda: None
        self.callbacks = []

    def subscribe(self, cb):
        self.callbacks.append(cb)

    def unsubscribe(self, cb):
        self.callbacks.remove(cb)

    def update(self, changed, deleted):
        # update local dictionary
        self.attribs.update(changed)
        for key in deleted:
            del self.attribs[key]

        if 'widget_label' in changed or 'widget_label_color' in changed:
            self.control.setLabel(get_color_string(self.attribs['widget_label'], self.attribs.get('widget_label_color')))
        if 'widget_icon' in changed:
            self.control.setProperty('iconurl', changed['widget_icon'])


    def set_separator_line(self, visible):
        self.control.setProperty('separator_line', '1' if visible else '0')

    def set_show_next_icon(self, visible):
        self.control.setProperty('show_next', '1' if visible else '0')

    def onAction(self, action):
        # base class does not support any actions
        pass

    def onClick(self):
        # base class does not support click actions
        pass


class ListItemSeparator(ListItem):
    def __init__(self):
        super(ListItemSeparator, self).__init__("separator", None)
        self.set_separator_line(True)


class ListItemLabel(ListItem):
    def __init__(self):
        super(ListItemLabel, self).__init__("label", None)

    def onClick(self):
        for cb in self.callbacks:
            cb(self)


class ListItemSwitch(ListItem):
    def __init__(self, proxy):
        super(ListItemSwitch, self).__init__("bool", proxy)

    def update(self, changed, deleted):
        super(ListItemSwitch, self).update(changed, deleted)
        if 'item_state' in changed:
            self.control.setProperty("value", '1' if changed['item_state'] else '0')

    def onClick(self):
        proxy = self.proxy()
        if proxy:
            new_value = not self.attribs['item_state']
            proxy.cmd_on() if new_value else proxy.cmd_off()

    def onAction(self, action):
        proxy = self.proxy()
        if proxy:
            if action.getId() == xbmcgui.ACTION_TELETEXT_RED:
                proxy.cmd_off()
            elif action.getId() == xbmcgui.ACTION_TELETEXT_GREEN:
                proxy.cmd_on()


class ListItemWithValue(ListItem):
    """List item with a value. The value is always of type str or unicode. The actual value is stored as nativeValue!
    """
    def __init__(self, typ, proxy):
        super(ListItemWithValue, self).__init__(typ, proxy)
        self.value = None

    def update(self, changed, deleted):
        super(ListItemWithValue, self).update(changed, deleted)
        if 'widget_value' in changed or 'widget_value_color' in changed:
            self.control.setProperty("value", get_color_string(self.attribs['widget_value'], self.attribs.get('widget_value_color')))


class ListItemText(ListItemWithValue):
    def __init__(self):
        super(ListItemText, self).__init__("text", None)

    def onClick(self):
        for cb in self.callbacks:
            cb(self)


class ListItemColor(ListItemWithValue):
    def __init__(self, proxy):
        super(ListItemColor, self).__init__("text", proxy)
        self.set_show_next_icon(True)
        self.dialog = None

    def update(self, changed, deleted):
        super(ListItemColor, self).update(changed, deleted)
        if self.dialog:
            if 'widget_label' in changed:
                self.dialog.set_title(changed['widget_label'])
            if 'item_state' in changed:
                self.dialog.set_color(hsv_degree_to_rgb_hex_str(self.attribs['item_state']))

    def onClick(self):
        proxy = self.proxy()
        if proxy:
            self.dialog = ColorPicker(self.attribs['widget_label'],
                                      hsv_degree_to_rgb_hex_str(self.attribs['item_state']))
            color = self.dialog.show()
            self.dialog = None
            if color is not None:
                proxy.cmd_set_hsv(rgb_hex_str_to_hsv_degree(color))


class ListItemSelection(ListItemWithValue):
    def __init__(self, proxy):
        super(ListItemSelection, self).__init__("text", proxy)
        self.set_show_next_icon(True)
        self.dialog = None

    def update(self, changed, deleted):
        super(ListItemSelection, self).update(changed, deleted)
        if self.dialog:
            if 'widget_label' in changed:
                self.dialog.set_title(changed['widget_label'])
            if 'widget_mapping' in changed:
                self.dialog.set_items(changed['widget_mapping'].itervalues())
            if 'item_state' in changed:
                self.dialog.set_index(get_item_index(self.attribs['widget_mapping'].keys(),
                                                     self.attribs['item_state']))

    def onClick(self):
        proxy = self.proxy()
        if proxy:
            self.dialog = SelectDialog(self.attribs['widget_label'],
                                       self.attribs['widget_mapping'].itervalues(),
                                       get_item_index(self.attribs['widget_mapping'].keys(),
                                                      self.attribs['item_state']))
            pos = self.dialog.show()
            self.dialog = None
            if pos is not None:
                (state, value) = self.attribs['widget_mapping'].items()[pos]
                proxy.cmd_set(state)


class ListItemSetPoint(ListItemWithValue):
    def __init__(self, proxy):
        super(ListItemSetPoint, self).__init__("text", proxy)
        self.set_show_next_icon(True)
        self.dialog = None

    def update(self, changed, deleted):
        super(ListItemSetPoint, self).update(changed, deleted)
        if self.dialog:
            if 'widget_label' in changed:
                self.dialog.set_title(changed['widget_label'])
            if 'widget_min_value' in changed or 'widget_max_value' in changed or 'widget_step' in changed:
                selections = list(reversed(list(drange(self.attribs['widget_min_value'],
                                                       self.attribs['widget_max_value'],
                                                       self.attribs['widget_step']))))
                self.dialog.set_items([str(x) for x in selections])
            if 'item_state' in changed:
                selections = list(reversed(list(drange(self.attribs['widget_min_value'],
                                                       self.attribs['widget_max_value'],
                                                       self.attribs['widget_step']))))
                self.dialog.set_index(get_item_index(selections, self.attribs['item_state']))

    def onAction(self, action):
        proxy = self.proxy()
        if proxy:
            state = None
            if action.getId() == xbmcgui.ACTION_CHANNEL_DOWN:
                state = self.attribs['item_state'] - self.attribs['widget_step']
            elif action.getId() == xbmcgui.ACTION_CHANNEL_UP:
                state = self.attribs['item_state'] + self.attribs['widget_step']

            if state is not None:
                if self.attribs['widget_min_value'] <= state <= self.attribs['widget_max_value']:
                    proxy.cmd_set(state)

    def onClick(self):
        proxy = self.proxy()
        if proxy:
            selections = list(reversed(list(drange(self.attribs['widget_min_value'],
                                                   self.attribs['widget_max_value'],
                                                   self.attribs['widget_step']))))
            self.dialog = SelectDialog(self.attribs['widget_label'],
                                       [str(x) for x in selections],
                                       get_item_index(selections, self.attribs['item_state']))
            pos = self.dialog.show()
            self.dialog = None
            if pos is not None:
                proxy.cmd_set(selections[pos])


class ListItemSlider(ListItemWithValue):
    def __init__(self, proxy):
        super(ListItemSlider, self).__init__("text", proxy)
        self.set_show_next_icon(True)
        self.dialog = None

    def update(self, changed, deleted):
        super(ListItemSlider, self).update(changed, deleted)
        if self.dialog:
            if 'widget_label' in changed:
                self.dialog.set_title(changed['widget_label'])
            if 'widget_mapping' in changed:
                self.dialog.set_items(changed['widget_mapping'].itervalues())
            if 'item_state' in changed:
                self.dialog.set_index(get_item_index(self.attribs['widget_mapping'].keys(), self.attribs['item_state']))

    def onAction(self, action):
        proxy = self.proxy()
        if proxy:
            state = None
            if action.getId() == xbmcgui.ACTION_TELETEXT_RED:
                proxy.cmd_off()
            elif action.getId() == xbmcgui.ACTION_TELETEXT_GREEN:
                proxy.cmd_on()
            elif action.getId() == xbmcgui.ACTION_CHANNEL_DOWN:
                proxy.cmd_decrement()
            elif action.getId() == xbmcgui.ACTION_CHANNEL_UP:
                proxy.cmd_increment()

    def onClick(self):
        proxy = self.proxy()
        if proxy:
            selections = list(reversed(list(drange(self.attribs['widget_min_value'],
                                                   self.attribs['widget_max_value'],
                                                   self.attribs['widget_step']))))
            self.dialog = SelectDialog(self.attribs['widget_label'],
                                       [str(x) for x in selections],
                                       get_item_index(selections, self.attribs['item_state']))
            pos = self.dialog.show()
            self.dialog = None
            if pos is not None:
                proxy.cmd_set(selections[pos])


class ListItemRollerShutter(ListItemWithValue):
    def __init__(self, proxy):
        super(ListItemRollerShutter, self).__init__("text", proxy)
        self.set_show_next_icon(True)
        self.dialog = None

    def onAction(self, action):
        proxy = self.proxy()
        if proxy:
            if action.getId() == xbmcgui.ACTION_CHANNEL_DOWN:
                proxy.cmd_down()
            elif action.getId() == xbmcgui.ACTION_CHANNEL_UP:
                proxy.cmd_up()
            elif action.getId() == xbmcgui.ACTION_STOP:
                proxy.cmd_stop()
            elif action.getId() == xbmcgui.ACTION_PLAY:
                proxy.cmd_move()

    def onClick(self):
        proxy = self.proxy()
        if proxy:
            selection = [ADDON.getLocalizedString(30202),
                         ADDON.getLocalizedString(30203),
                         ADDON.getLocalizedString(30204)]
            self.dialog = SelectDialog(self.attribs['widget_label'], selection, 1)
            pos = self.dialog.show()
            self.dialog = None
            if pos is not None:
                if pos == 0:
                    proxy.cmd_up()
                elif pos == 1:
                    proxy.cmd_stop()
                elif pos == 2:
                    proxy.cmd_down()


class WidgetList(object):
    def __init__(self, control):
        self.items = []
        self.control = control  # store xbmcgui.ControlList
        self.select_valid = False   # True = a non separator line is already selected

    def reset(self):
        del self.items[:]
        self.control.reset()

    def add_item(self, item):
        # add item to local list
        self.items.append(item)
        # add item to xbmcgui.ListControl
        self.control.addItem(item.control)

    def get_selected_position(self):
        return self.control.getSelectedPosition()

    def select_item(self, pos):
        self.control.selectItem(pos)

    def select_first_item(self):
        pos = 0
        for item in self.items:
            if item.control.getProperty('type') != 'separator':
                self.control.selectItem(pos)
                return
            pos += 1

    def add_separator_line_to_last_item(self):
        if self.items:
            self.items[-1].set_separator_line(True)

    def onAction(self, action):
        # test if action is either up/down/right to set focus correctly
        diff = FOCUS_CHANGED_CODES.get(action.getId())
        if diff is not None:
            # skip separator lines which can't have the focus
            size = self.control.size()
            pos = self.control.getSelectedPosition()
            if pos >= 0:
                while self.items[pos].control.getProperty('type') == 'separator':
                    pos += diff
                    if pos < 0:
                        pos = size - 1
                    elif pos >= size:
                        pos = 0
                self.control.selectItem(pos)
        else:
            # any other action
            pos = self.get_selected_position()
            if pos < 0:
                debugPrint(1, 'WidgetList [%d]::onAction [%d], but nothing selected'
                           % (self.control.getId(), action.getId()))
                return
            elif pos >= len(self.items):
                debugPrint(1, 'WidgetList [%d]::onAction [%d], index out of range (pos=%d, len=%d)'
                           % (self.control.getId(), action.getId(), pos, len(self.items)))
                return
            self.items[pos].onAction(action)

    def onClick(self):
        pos = self.get_selected_position()
        if pos < 0:
            debugPrint(1, 'WidgetList [%d]::onClick, but nothing selected' % self.control.getId())
            return
        self.items[pos].onClick()


class MainWindow(xbmcgui.WindowXMLDialog):
    def __new__(cls):
        return super(MainWindow, cls).__new__(cls, "menulist.xml", xbmcaddon.Addon().getAddonInfo('path'))

    # init window
    def __init__(self):
        super(MainWindow, self).__init__()
        self.list = None

    def build_menu(self):
        pass

    def go_back(self):
        """Dummy function for derived classes"""
        pass

    # window init callback
    def onInit(self):
        self.list = WidgetList(self.getControl(CONTROL_ID_LIST))
        self.build_menu()
        self.setFocusId(CONTROL_ID_LIST)

    # window action callback
    def onAction(self, action):
        if action.getId() in WINDOW_EXIT_CODES:
            self.go_back()
        else:
            # forward action to active control
            focusId = self.getFocusId()
            if focusId == CONTROL_ID_LIST:
                self.list.onAction(action)

    # mouse click action
    def onClick(self, controlId):
        if controlId == CONTROL_ID_LIST:
            self.list.onClick()
