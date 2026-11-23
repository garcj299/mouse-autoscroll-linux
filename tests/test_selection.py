import unittest

from mouse_autoscroll.engine import BTN_LEFT, BTN_MIDDLE, BTN_RIGHT, EV_KEY, EV_REL
from mouse_autoscroll.selection import is_autoscroll_mouse

BTN_SIDE, BTN_EXTRA = 0x113, 0x114
EV_ABS = 0x03

# Real nodes on cyriaendureo, 2026-11-23
USB_MOUSE = dict(
    props={"ID_INPUT": "1", "ID_INPUT_MOUSE": "1"},
    sys_path="/sys/devices/pci0000:00/0000:00:14.0/usb3/3-1/input/input22/event17",
    caps={EV_KEY: [BTN_LEFT, BTN_RIGHT, BTN_MIDDLE, BTN_SIDE, BTN_EXTRA],
          EV_REL: [0, 1, 8, 11]},
)
TRACKPOINT = dict(
    props={"ID_INPUT": "1", "ID_INPUT_MOUSE": "1", "ID_INPUT_POINTINGSTICK": "1"},
    sys_path="/sys/devices/platform/i8042/serio1/input/input6/event7",
    caps={EV_KEY: [BTN_LEFT, BTN_RIGHT, BTN_MIDDLE], EV_REL: [0, 1]},
)
ELAN_BUTTONS = dict(
    props={"ID_INPUT": "1", "ID_INPUT_MOUSE": "1", "ID_INPUT_POINTINGSTICK": "0"},
    sys_path="/sys/devices/pci0000:00/0000:00:15.0/i2c-ELAN06C6:00/input/input10/event5",
    caps={EV_KEY: [BTN_LEFT, BTN_RIGHT], EV_REL: [0, 1]},
)
TOUCHPAD = dict(
    props={"ID_INPUT": "1", "ID_INPUT_TOUCHPAD": "1"},
    sys_path="/sys/devices/pci0000:00/i2c-ELAN06C6:00/input/input11/event6",
    caps={EV_KEY: [BTN_LEFT], EV_ABS: [0, 1, 53, 54]},
)


class SelectionTest(unittest.TestCase):
    def test_usb_mouse_selected(self):
        self.assertTrue(is_autoscroll_mouse(**USB_MOUSE))

    def test_trackpoint_excluded(self):
        self.assertFalse(is_autoscroll_mouse(**TRACKPOINT))

    def test_node_without_middle_button_excluded(self):
        self.assertFalse(is_autoscroll_mouse(**ELAN_BUTTONS))

    def test_touchpad_excluded(self):
        self.assertFalse(is_autoscroll_mouse(**TOUCHPAD))

    def test_virtual_devices_excluded(self):
        clone = dict(USB_MOUSE, sys_path="/sys/devices/virtual/input/input99/event30")
        self.assertFalse(is_autoscroll_mouse(**clone))

    def test_bluetooth_mouse_selected(self):
        bt = dict(USB_MOUSE, sys_path="/sys/devices/.../bluetooth/hci0/hci0:256/input30/event20")
        self.assertTrue(is_autoscroll_mouse(**bt))

    def test_absolute_pointer_with_middle_excluded(self):
        tablet = dict(
            props={"ID_INPUT": "1", "ID_INPUT_MOUSE": "1"},
            sys_path="/sys/devices/pci0000:00/usb1/input/input40/event25",
            caps={EV_KEY: [BTN_LEFT, BTN_MIDDLE], EV_REL: [8], EV_ABS: [0, 1]},
        )
        self.assertFalse(is_autoscroll_mouse(**tablet))

    def test_tablet_and_joystick_flags_excluded(self):
        for flag in ("ID_INPUT_TABLET", "ID_INPUT_JOYSTICK"):
            dev = dict(USB_MOUSE, props={**USB_MOUSE["props"], flag: "1"})
            self.assertFalse(is_autoscroll_mouse(**dev), flag)

    def test_not_marked_mouse_excluded(self):
        dev = dict(USB_MOUSE, props={"ID_INPUT": "1", "ID_INPUT_KEYBOARD": "1"})
        self.assertFalse(is_autoscroll_mouse(**dev))


if __name__ == "__main__":
    unittest.main()
