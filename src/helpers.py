# -*- coding: utf-8 -*-
# Copyright (c) 2014-18 Richard Hull and contributors
# See LICENSE.rst for details.

import sys
import logging
import warnings

from luma.core import cmdline, error
from luma.core.virtual import snapshot, canvas, viewport
from PIL import ImageDraw
from PIL.ImageFont import FreeTypeFont
from dataclasses import dataclass

@dataclass
class Animation:
    """
        obj_start (tuple[int, int]): Coordinates (x, y) of the object at the start of the animation. The object will jump to this location
                                     at the start of the animation.
        obj_end (tuple[int, int]): End coordinates (x, y) of the object. The object will move to this location by the end of the animation.
        viewport_start (tuple[int, int]): TODO: Not implemented
        viewport_end (tuple[int, int]): TODO: Not implemented
        start_delay (int, optional): Delay before animation starts. Defaults to 0.
    """
    obj_start: tuple[int, int]
    obj_end: tuple[int, int]

    viewport_start: tuple[int, int]
    viewport_end: tuple[int, int]

    start_delay: int = 0

@dataclass
class AnimationSequence:
    sequence: list[Animation]
    interval: float
    refresh_animation: Animation | None = None

@dataclass
class BoundingBox:
    start: tuple[int, int]
    end: tuple[int, int]

@dataclass
class RenderText:
    text: str
    font: FreeTypeFont


class AnimatedObject:

    luma_snapshot: snapshot
    animation_counter: int = 0
    animation_index: int = 0

    def __init__(self, device, xy: tuple[int, int], text: list[RenderText], viewport: BoundingBox | None = None) -> None:
        """Creates a text object with optional animations

        Args:
            device (_type_): _description_
            xy (tuple[int, int]): Coordinates of object's top left corner
            text (list[RenderText]): Text to display. List of RenderText objects (combined text strings and font).
            viewport (BoundingBox | None, optional): Bounding box dimensions. All object content within the viewport will be
                                                     shown, all other content will be clipped. Defaults to None, where no clipping occurs.
        """

        # Determine dimensions of object
        self.width = 0
        self.height = 0
        with canvas(device) as draw:
            for t in text:                
                (x1, y1, x2, y2) = draw.textbbox((0, 0), t.text, t.font)
                h = y2 - y1
                if h > self.height:
                    self.height = h

                self.width += x2 - x1
        
        
        if viewport is None:
            self.viewport = BoundingBox(
                start=xy,
                end=(xy[0] + self.width, xy[1] + self.height)
            )
        else:
            self.viewport = viewport

        self.viewport_width = self.viewport.end[0] - self.viewport.start[0]
        self.viewport_height = self.viewport.end[1] - self.viewport.start[1]
        
        self.current_x = xy[0]
        self.current_y = xy[1]
        self.start_pos = xy
        self.text = text
        
        self.animations: AnimationSequence | None = None

    
    def add_animations(self, animations: AnimationSequence) -> None:
        """Add an AnimationSequence to the AnimatedObject

        Args:
            animations (AnimationSequence): AnimationSequence object
        """
        self.animations = animations

    def create_hotspot(self, width: int, height: int) -> snapshot:
        if self.animations is not None:
            interval = self.animations.interval
        else:
            interval = 1

        self.luma_snapshot = snapshot(width, self.height, draw_fn=self.update, interval=interval)
        return self.luma_snapshot
        
    def update(self, draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
        x_offset = 0

        for t in self.text:
            draw.text((x_offset + self.current_x - self.start_pos[0], self.current_y - self.start_pos[1]), t.text, font=t.font, fill="yellow")
            x_offset += int(draw.textlength(t.text, t.font))
        
        if self.animations is not None and len(self.animations.sequence) != 0:

            current_animation = self.animations.sequence[self.animation_index]

            if self.animation_counter < current_animation.start_delay:
                self.animation_counter += 1
                return
            elif self.animation_counter == current_animation.start_delay:
                self.current_x = current_animation.obj_start[0]
                self.current_y = current_animation.obj_start[1]

            delta_x = current_animation.obj_end[0] - current_animation.obj_start[0]
            delta_y = current_animation.obj_end[1] - current_animation.obj_start[1]

            # https://stackoverflow.com/a/52355075
            sign = lambda x: -1 if x < 0 else (1 if x > 0 else 0)

            x_complete = self.current_x == current_animation.obj_end[0]
            y_complete = self.current_y == current_animation.obj_end[1]

            # print("x", self.current_x, current_animation.obj_end[0], x_complete)
            # print("y", self.current_y, current_animation.obj_end[1], y_complete)

            if not x_complete:
                self.current_x += sign(delta_x)

            if not y_complete:
                self.current_y += sign(delta_y)
            
            # If the animation is complete, reset the animation counter,
            # and move on to the next animation in the sequence list
            if x_complete and y_complete:
                self.animation_counter = 0

                self.animation_index += 1
                self.animation_index = self.animation_index % len(self.animations.sequence)

            else:
                self.animation_counter += 1


def move_object(xy: tuple[int, int], delay: int = 0) -> Animation:
    return Animation(
        obj_start=xy, obj_end=xy, viewport_start=(0, 0), viewport_end=(0, 0), start_delay=delay
    )

def reset_object(obj: AnimatedObject, delay: int = 0) -> Animation:
    return move_object(obj.start_pos, delay)

def scroll_left(obj: AnimatedObject, delay: int = 0) -> Animation:
    return Animation(
        obj_start=obj.start_pos,
        obj_end=(obj.start_pos[0] - obj.width, obj.start_pos[1]),
        viewport_start=(0, 0), viewport_end=(0, 0),
        start_delay=delay
    )

def scroll_up(obj: AnimatedObject, start_pos: tuple[int, int] | None = None, delay: int = 0) -> Animation:
    if start_pos is None:
        start_pos = obj.start_pos
    return Animation(
        obj_start=(start_pos[0], start_pos[1] + obj.height),
        obj_end=obj.start_pos,
        viewport_start=(0, 0), viewport_end=(0, 0),
        start_delay=delay
    )


class ObjectRow:
    def __init__(self, objects: list[AnimatedObject], display_width: int) -> None:
        self.objects = objects
        self.display_width = display_width
        
        self.height = 0
        for obj in objects:
            if obj.height > self.height:
                self.height = obj.height

    def add_hotspots(self, y: int, viewport: viewport) -> viewport:

        current_x = 0
        for obj in self.objects:
            if current_x + obj.viewport_width > self.display_width:
                width = self.display_width - current_x
            else:
                width = obj.viewport_width

            if width > 0:
                hs = obj.create_hotspot(width, obj.viewport_height)
                viewport.add_hotspot(hs, (current_x, y))
            else:
                warnings.warn(f"Could not display object: {obj}")

            current_x += width

        return viewport



# logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)-15s - %(message)s'
)
# ignore PIL debug messages
logging.getLogger('PIL').setLevel(logging.ERROR)


def display_settings(args):
    """
    Display a short summary of the settings.

    :rtype: str
    """
    iface = ''
    display_types = cmdline.get_display_types()
    if args.display not in display_types['emulator']:
        iface = 'Interface: {}\n'.format(args.interface)

    lib_name = cmdline.get_library_for_display_type(args.display)
    if lib_name is not None:
        lib_version = cmdline.get_library_version(lib_name)
    else:
        lib_name = lib_version = 'unknown'

    import luma.core
    version = 'luma.{} {} (luma.core {})'.format(
        lib_name, lib_version, luma.core.__version__)

    return 'Version: {}\nDisplay: {}\n{}Dimensions: {} x {}\n{}'.format(
        version, args.display, iface, args.width, args.height, '-' * 60)


def get_device(actual_args=None):
    """
    Create device from command-line arguments and return it.
    """
    if actual_args is None:
        actual_args = sys.argv[1:]
    parser = cmdline.create_parser(description='luma.examples arguments')
    args = parser.parse_args(actual_args)

    if args.config:
        # load config from file
        config = cmdline.load_config(args.config)
        args = parser.parse_args(config + actual_args)

    # create device
    try:
        device = cmdline.create_device(args)
    except error.Error as e:
        parser.error(str(e))

    return device
