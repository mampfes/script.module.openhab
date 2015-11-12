# coding=utf-8

import xbmc
import xbmcaddon

ADDON = xbmcaddon.Addon()


def debugPrint(level, msg):
    msg = unicode(msg)
    if level == 0:
        level = xbmc.LOGERROR
    elif level < 3:
        level = xbmc.LOGWARNING
    elif level < 5:
        level = xbmc.LOGNOTICE
    else:
        if ADDON.getSetting('debug') == 'true':
            level = xbmc.LOGNOTICE
        else:
            level = xbmc.LOGDEBUG
    xbmc.log(u"{0}".format(msg).encode('ascii', 'xmlcharrefreplace'), level)