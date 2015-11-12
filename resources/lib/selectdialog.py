# coding=utf-8

import xbmcaddon
import xbmcgui

# selectdialog.xml control ID's
CONTROL_ID_LIST = 1100

# xbmcgui action codes to go up/back in a window
WINDOW_EXIT_CODES = frozenset([xbmcgui.ACTION_PARENT_DIR,
                               xbmcgui.ACTION_PREVIOUS_MENU,
                               xbmcgui.ACTION_NAV_BACK,
                               xbmcgui.KEY_BUTTON_BACK])


class SelectDialog(xbmcgui.WindowXMLDialog):
    def __new__(cls, title, items, index=0):
        return super(SelectDialog, cls).__new__(cls, "selectdialog.xml", xbmcaddon.Addon().getAddonInfo('path'))

    # init window
    def __init__(self, title, items, index=None):
        super(SelectDialog, self).__init__()
        self.control = None
        self.title = title
        self.items = items
        self.index = index
        self.result = None
        self.listitems = []

    def show(self):
        self.doModal()
        return self.result

    def set_title(self, title):
        self.title = title
        if self.control:
            self.setProperty('title', self.title)

    def set_items(self, items):
        self.items = items
        # rebuild whole menu if item list has changed
        self.build_list()

    def set_index(self, index):
        if self.index is not None:
            self.listitems[self.index].select(False)
        self.index = index
        if self.index is not None:
            self.listitems[self.index].select(True)

    def build_list(self):
        self.control.reset()
        self.listitems = []
        for x in self.items:
            li = xbmcgui.ListItem(label=x)
            self.listitems.append(li)
            self.control.addItem(li)

        if self.index is not None:
            self.listitems[self.index].select(True)     # set selected flag
            self.control.selectItem(self.index)         # move focus to selected item

    # window init callback
    def onInit(self):
        self.control = self.getControl(CONTROL_ID_LIST)
        self.build_list()
        self.setProperty('title', self.title)
        self.setFocusId(CONTROL_ID_LIST)

    # window action callback
    def onAction(self, action):
        if action.getId() in WINDOW_EXIT_CODES:
            self.close()

    # mouse click action
    def onClick(self, controlId):
        if controlId == CONTROL_ID_LIST:
            self.result = self.control.getSelectedPosition()
        self.close()
