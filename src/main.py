import os
import sys
import time
import json
import requests

from datetime import datetime
from PIL import ImageFont, Image, ImageDraw
from helpers import get_device, AnimatedObject, RenderText, Animation, AnimationSequence, move_object, scroll_left, scroll_up, ObjectRow, reset_object
from trains import loadDeparturesForStationRTT, ProcessedDepartures, CallingPoints
from luma.core.render import canvas
from luma.core.virtual import viewport, snapshot
from open import isRun
from typing import Any, List, Tuple
from luma.core.interface.serial import spi, noop
from luma.oled.device import ssd1322
from luma.core.virtual import viewport, snapshot
from luma.core.sprite_system import framerate_regulator
import socket, re, uuid

global toc
DISPLAY_WIDTH = 256
DISPLAY_HEIGHT = 64

def loadConfig() -> dict[str, Any]:
    with open('config.json', 'r') as jsonConfig:
        data = json.load(jsonConfig)
        return data

def makeFont(name, size):
    font_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'fonts', name))
    return ImageFont.truetype(font_path, size, layout_engine=ImageFont.Layout.BASIC)

def format_hhmm(timestamp: str) -> str:
    return f"{timestamp[0:2]}:{timestamp[2:4]}"

def renderDestination(departure: ProcessedDepartures, font, pos):
    departureTime = departure.aimed_departure_time
    destinationName = departure.destination_name

    def drawText(draw, *_):
        train = f"{departureTime}  {destinationName}"
        _, _, bitmap = cachedBitmapText(train, font)
        draw.bitmap((0, 0), bitmap, fill="yellow")

    return drawText

def renderServiceStatus(departure: ProcessedDepartures):
    def drawText(draw, width, *_):
        train = ""
        if departure.status in ["CANCELLED", "CANCELLED_CALL", "CANCELLED_PASS"]:
            train = "Cancelled"
        else:
            if isinstance(departure.expected_departure_time, str):
                train = 'Exp ' + departure.expected_departure_time
            if departure.expected_departure_time == departure.expected_departure_time:
                train = "On time"
        
        w, _, bitmap = cachedBitmapText(train, font)
        draw.bitmap((width - w, 0), bitmap, fill="yellow")
    return drawText

def renderPlatform(departure: ProcessedDepartures):
    def drawText(draw, *_):
        if departure.mode == "bus":
            draw.text((0, 0), text="BUS", font=font, fill="yellow")
        else:
            if isinstance(departure.platform, str):
                platform = "Plat " + departure.platform
                _, _, bitmap = cachedBitmapText(platform, font)
                draw.bitmap((0, 0), bitmap, fill="yellow")
    return drawText

def renderCallingAt(draw, *_):
    stations = "Calling at:"
    _, _, bitmap = cachedBitmapText(stations, font)
    draw.bitmap((0, 0), bitmap, fill="yellow")

bitmapRenderCache = {}

def cachedBitmapText(text, font):
    text = str(text)
    nameTuple = font.getname()
    fontKey = ''
    for item in nameTuple:
        fontKey = fontKey + item
    key = text + fontKey
    if key in bitmapRenderCache:
        pre = bitmapRenderCache[key]
        bitmap = pre['bitmap']
        txt_width = pre['txt_width']
        txt_height = pre['txt_height']
    else:
        _, _, txt_width, txt_height = font.getbbox(text)
        bitmap = Image.new('L', [txt_width, txt_height], color=0)
        pre_render_draw = ImageDraw.Draw(bitmap)
        pre_render_draw.text((0, 0), text=text, font=font, fill=255)
        bitmapRenderCache[key] = {'bitmap': bitmap, 'txt_width': txt_width, 'txt_height': txt_height}
    return txt_width, txt_height, bitmap

pixelsLeft = 1
pixelsUp = 0
hasElevated = 0
pauseCount = 0

def get_stations_string(stations: list[CallingPoints], toc: str) -> str:
    if not stations:
        return "No calling points available."
    if len(stations) == 1:
        calling_at_str = f"{stations[0].station} ({format_hhmm(stations[0].arrival_time)}) only."
    else:
        calling_at_str = ", ".join([f"{call.station} ({format_hhmm(call.arrival_time)})" for call in stations[:-1]])
        calling_at_str += f" and {stations[-1].station} ({format_hhmm(stations[-1].arrival_time)})."
    calling_at_str += f"    (A {toc} service.)"
    return calling_at_str


def renderStations(stations: list[CallingPoints], toc: str, departure_station: str):
    print(f"Original calling points: {[s.station for s in stations]}")

    departure_station = departure_station.strip().lower()

    departure_index = next((index for (index, d) in enumerate(stations) if d.station.strip().lower() == departure_station), None)

    print(f"Departure station: {departure_station}, Matched index: {departure_index}")

    if departure_index is not None:
        stations = stations[departure_index + 1:]

    print(f"Filtered calling points: {[s.station for s in stations]}")

    calling_at_str = get_stations_string(stations, toc)

    def drawText(draw, *_):
        global stationRenderCount, pauseCount, pixelsLeft, pixelsUp, hasElevated
        if len(stations) == stationRenderCount - 5:
            stationRenderCount = 0
        txt_width, txt_height, bitmap = cachedBitmapText(calling_at_str, font)
        if hasElevated:
            draw.bitmap((pixelsLeft - 1, 0), bitmap, fill="yellow")
            if -pixelsLeft > txt_width and pauseCount < 8:
                pauseCount += 1
                pixelsLeft = 0
                hasElevated = 0
            else:
                pauseCount = 0
                pixelsLeft = pixelsLeft - 1
        else:
            draw.bitmap((0, txt_height - pixelsUp), bitmap, fill="yellow")
            if pixelsUp == txt_height:
                pauseCount += 1
                if pauseCount > 20:
                    hasElevated = 1
                    pixelsUp = 0
            else:
                pixelsUp = pixelsUp + 1
    return drawText


def renderTime(draw, width, *_):
    rawTime = datetime.now().time()
    hour, minute, second = str(rawTime).split('.')[0].split(':')
    w1, _, HMBitmap = cachedBitmapText("{}:{}".format(hour, minute), fontBoldLarge)
    w2, _, _ = cachedBitmapText(':00', fontBoldTall)
    _, _, SBitmap = cachedBitmapText(':{}'.format(second), fontBoldTall)
    draw.bitmap(((width - w1 - w2) / 2, 0), HMBitmap, fill="yellow")
    draw.bitmap((((width - w1 - w2) / 2) + w1, 5), SBitmap, fill="yellow")

def renderDebugScreen(lines):
    def drawDebug(draw, *_):
        draw.rectangle((1, 1, 254, 45), outline="yellow", fill=None)
        coords = {
            '1A': (5, 5),
            '1B': (45, 5),
            '2A': (5, 18),
            '2B': (45, 18),
            '3A': (5, 31),
            '3B': (45, 31),
            '3C': (140, 31)
        }
        for key, text in lines.items():
            w, _, bitmap = cachedBitmapText(text, font)
            draw.bitmap(coords[key], bitmap, fill="yellow")        
    return drawDebug

def renderWelcomeTo(xOffset):
    def drawText(draw, *_):
        text = "Welcome to"
        draw.text((int(xOffset), 0), text=text, font=fontBold, fill="yellow")
    return drawText
    
def renderDepartureStation(departureStation, xOffset):
    def draw(draw, *_):
        text = departureStation
        draw.text((int(xOffset), 0), text=text, font=fontBold, fill="yellow")
    return draw

def renderDots(draw, *_):
    text = ".  .  ."
    draw.text((0, 0), text=text, font=fontBold, fill="yellow")

def loadDestinationsForDepartureRTT(journeyConfig: dict[str, Any], username: str, password: str, timetableUrl: str) -> List[CallingPoints]:
    r = requests.get(url=timetableUrl, auth=(username, password))
    calling_data = r.json()

    print("API response from service:", json.dumps(calling_data, indent=2))

    departure_crs = journeyConfig["departureStation"].strip().lower()
    index = 0
    for loc in calling_data['locations']:
        if loc['crs'].strip().lower() == departure_crs:
            break
        index += 1

    print(f"Departure CRS: {departure_crs}, Stations: {[loc['crs'] for loc in calling_data['locations'][index+1:]]}")

    calling_at = []
    for loc in calling_data['locations'][index+1:]:
        calling_at.append(
            CallingPoints(loc['description'], loc["realtimeArrival"])
        )

    return calling_at

def loadDataRTT(apiConfig: dict[str, Any], journeyConfig: dict[str, Any]) -> Tuple[List[ProcessedDepartures], List[CallingPoints], str]:
    runHours = [int(x) for x in apiConfig['operatingHours'].split('-')]
    if not isRun(runHours[0], runHours[1]):
        return [], [], journeyConfig['outOfHoursName']

    departures, stationName = loadDeparturesForStationRTT(journeyConfig, apiConfig["username"], apiConfig["password"])

    if len(departures) == 0:
        return [], [], journeyConfig['outOfHoursName']

    firstDepartureDestinations = loadDestinationsForDepartureRTT(journeyConfig, apiConfig["username"], apiConfig["password"], departures[0].timetable_url)

    return departures, firstDepartureDestinations, stationName

def drawBlankSignage(device, width: int, height: int, departureStation: str):
    global stationRenderCount, pauseCount
    welcomeSize = int(fontBold.getlength("Welcome to"))
    stationSize = int(fontBold.getlength(departureStation))
    device.clear()
    virtualViewport = viewport(device, width=width, height=height)
    
    rowOne = snapshot(width, 10, renderWelcomeTo(
         (width - welcomeSize) / 2), interval=10)
    rowTwo = snapshot(width, 10, renderDepartureStation(
        departureStation, (width - stationSize) / 2), interval=10)
    rowThree = snapshot(width, 10, renderDots, interval=10)
    rowTime = snapshot(width, 14, renderTime, interval=0.1)
    
    if len(virtualViewport._hotspots) > 0:
        for vhotspot, xy in virtualViewport._hotspots:
            virtualViewport.remove_hotspot(vhotspot, xy)
    virtualViewport.add_hotspot(rowOne, (0, 0))
    virtualViewport.add_hotspot(rowTwo, (0, 12))
    virtualViewport.add_hotspot(rowThree, (0, 24))
    virtualViewport.add_hotspot(rowTime, (0, 50))
    return virtualViewport

def drawSignage(device, width, height, data):
    global stationRenderCount, pauseCount
    virtualViewport = viewport(device, width=width, height=height)
    status = "Exp 00:00"
    callingAt = "Calling at: "
    departures, firstDepartureDestinations, departureStation = data
    w = int(font.getlength(callingAt))
    callingWidth = w
    width = virtualViewport.width
    w = int(font.getlength(status))
    pw = int(font.getlength("Plat 88"))
    if len(departures) == 0:
        noTrains = drawBlankSignage(device, width=width, height=height, departureStation=departureStation)
        return noTrains
    firstFont = font
    firstFont = fontBold
        
    rowOneA = snapshot(width - w - pw - 5, 10, renderDestination(departures[0], firstFont, '1st'), interval=10)
    rowOneB = snapshot(w, 10, renderServiceStatus(departures[0]), interval=10)
    rowOneC = snapshot(pw, 10, renderPlatform(departures[0]), interval=10)
    rowTwoA = snapshot(callingWidth, 10, renderCallingAt, interval=100)
    rowTwoB = snapshot(width - callingWidth, 10,
                       renderStations(firstDepartureDestinations, departures[0].toc, departureStation), interval=0.02)  
    if len(departures) > 1:
        rowThreeA = snapshot(width - w - pw, 10, renderDestination(departures[1], font, '2nd'), interval=10)
        rowThreeB = snapshot(w, 10, renderServiceStatus(departures[1]), interval=10)
        rowThreeC = snapshot(pw, 10, renderPlatform(departures[1]), interval=10)
    if len(departures) > 2:
        rowFourA = snapshot(width - w - pw, 10, renderDestination(departures[2], font, '3rd'), interval=10)
        rowFourB = snapshot(w, 10, renderServiceStatus(departures[2]), interval=10)
        rowFourC = snapshot(pw, 10, renderPlatform(departures[2]), interval=10)
    rowTime = snapshot(width, 14, renderTime, interval=0.1)
    if len(virtualViewport._hotspots) > 0:
        for vhotspot, xy in virtualViewport._hotspots:
            virtualViewport.remove_hotspot(vhotspot, xy)
    stationRenderCount = 0
    pauseCount = 0
    virtualViewport.add_hotspot(rowOneA, (0, 0))
    virtualViewport.add_hotspot(rowOneB, (width - w, 0))
    virtualViewport.add_hotspot(rowOneC, (width - w - pw, 0))
    virtualViewport.add_hotspot(rowTwoA, (0, 12))
    virtualViewport.add_hotspot(rowTwoB, (callingWidth, 12))
    if len(departures) > 1:
        virtualViewport.add_hotspot(rowThreeA, (0, 24))
        virtualViewport.add_hotspot(rowThreeB, (width - w, 24))
        virtualViewport.add_hotspot(rowThreeC, (width - w - pw, 24))
    if len(departures) > 2:
        virtualViewport.add_hotspot(rowFourA, (0, 36))
        virtualViewport.add_hotspot(rowFourB, (width - w, 36))
        virtualViewport.add_hotspot(rowFourC, (width - w - pw, 36))
    virtualViewport.add_hotspot(rowTime, (0, 50))
    return virtualViewport

try:
    serial = spi(port=0)
    device = ssd1322(serial, mode="1", rotate=2)
    config = loadConfig()
    font = makeFont("Dot Matrix Regular.ttf", 10)
    fontBold = makeFont("Dot Matrix Bold.ttf", 10)
    fontBoldTall = makeFont("Dot Matrix Bold Tall.ttf", 10)
    fontBoldLarge = makeFont("Dot Matrix Bold.ttf", 20)
    widgetWidth = 256
    widgetHeight = 64
    stationRenderCount = 0
    pauseCount = 0
    loop_count = 0
    
    if config["apiMethod"] == 'rtt':
        data = loadDataRTT(config["rttApi"], config["journey"])
    else:
        raise Exception(f"Unsupported apiMethod: {config['apiMethod']}")
        
    if len(data[0]) == 0:
        virtual = drawBlankSignage(
            device, width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT, departureStation=data[2])
    else:
        virtual = drawSignage(device, width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT, data=data)
    timeAtStart = time.time()
    timeNow = time.time()
    while True:
        if (timeNow - timeAtStart >= config["refreshTime"]):
            if config["apiMethod"] == 'rtt':
                data = loadDataRTT(config["rttApi"], config["journey"])
            if len(data[0]) == 0:
                virtual = drawBlankSignage(
                    device, width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT, departureStation=data[2])
            else:
                departureData = data[0]
                nextStations = data[1]
                station = data[2]
                virtual = drawSignage(device, width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT, data=data)
                # virtual = drawDebugScreen(device, width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT, showTime=True)
                
            timeAtStart = time.time()
        timeNow = time.time()
        virtual.refresh()
        
except KeyboardInterrupt:
    pass
except ValueError as err:
    print(f"Error: {err}")
except requests.RequestException as err:
    print(f"Request Error: {err}")
