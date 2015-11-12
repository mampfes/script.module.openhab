# coding=utf-8

import colorsys


def hex_str_to_tuple(hex_str):
    """Returns a tuple representing the given hex string (as used for RGB)

    >>> hex_str_to_tuple('CC0000')
    (204, 0, 0)
    """
    if hex_str.startswith('#'):
        hex_str = hex_str[1:]
    return tuple([int(hex_str[i:i + 2], 16) for i in xrange(0, len(hex_str), 2)])


def tuple_to_hex_str(rgb):
    """Converts an rgb tuple to hex string for web.

    >>> tuple_to_hex_str((204, 0, 0))
    'CC0000'
    """
    return ''.join(["%0.2X" % c for c in rgb])


def scale_rgb_tuple_down(rgb):
    """Scales an RGB tuple down to values between 0 and 1.

    >>> scale_rgb_tuple_down((204, 0, 0))
    (.80, 0, 0)
    """
    return tuple([round(float(c)/255, 2) for c in rgb])


def scale_rgb_tuple_up(rgb):
    """Scales an RGB tuple up from values between 0 and 1.

    >>> scale_rgb_tuple_up((.80, 0, 0))
    (204, 0, 0)
    """
    return tuple([int(round(c*255)) for c in rgb])


def scale_hsv_tuple_down(hsv):
    """Scales a HSV tuple down to values between 0 and 1.

    >>> scale_hsv_tuple_down((360, 100, 100))
    (1., 1., 1.)
    """
    return hsv[0]/360, hsv[1]/100, hsv[2]/100


def scale_hsv_tuple_up(hsv):
    """Scales a HSV tuple up to values between 360° for H and 100% for S and V.

    >>> scale_hsv_tuple_up((1., 1., 1.))
    (360., 100., 100.)
    """
    return hsv[0]*360, hsv[1]*100, hsv[2]*100


def hsv_degree_to_rgb_hex_str(hsv):
    hsv_down = scale_hsv_tuple_down(hsv)
    rgb = colorsys.hsv_to_rgb(*hsv_down)
    rgb_hex = scale_rgb_tuple_up(rgb)
    return tuple_to_hex_str(rgb_hex)


def rgb_hex_str_to_hsv_degree(rgb_hex_str):
    rgb_hex = hex_str_to_tuple(rgb_hex_str)
    rgb2 = scale_rgb_tuple_down(rgb_hex)
    hsv_down2 = colorsys.rgb_to_hsv(*rgb2)
    return scale_hsv_tuple_up(hsv_down2)
