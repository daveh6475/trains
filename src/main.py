import os
import sys
import time
import json
import requests
from datetime import datetime
from PIL import ImageFont, Image, ImageDraw
from helpers import get_device, AnimatedObject, RenderText, Animation, AnimationSequence, move_object, scroll_left, scroll_up, ObjectRow, reset_object
from trains import loadDeparturesForStation
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

def renderDepartureDetails(departure, font, pos):
    departureTime = departure["aimed_departure_time"]
    destinationName = departure["destination_name"]
    serviceMessage = departure.get("service_message", "")
    carriagesMessage = departure.get("carriages_message", "")

    def drawText(draw, *_):
        y_offset = 0
        train = f"{departureTime}  {destinationName}"
        _, _, bitmap = cachedBitmapText(train, font)
        draw.bitmap((0, y_offset), bitmap, fill="yellow")
        y_offset += 10
        
        if serviceMessage:
            _, _, bitmap = cachedBitmapText(serviceMessage, font)
            draw.bitmap((0, y_offset), bitmap, fill="yellow")
            y_offset += 10
        
        if carriagesMessage:
            _, _, bitmap = cachedBitmapText(carriagesMessage, font)
            draw.bitmap((0, y_offset), bitmap, fill="yellow")
            y_offset += 10

    return drawText

def renderServiceStatus(departure):
    def drawText(draw, width, *_):
        train = ""

        if departure["expected_departure_time"] == "On time":
            train = "On time"
        elif departure["expected_departure_time"] == "Cancelled":
            train = "Cancelled"
        elif departure["expected_departure_time"] == "Delayed":
            train = "Delayed"
        else:
            if isinstance(departure["expected_departure_time"], str):
                train = 'Exp ' + departure["expected_departure_time"]

            if departure["aimed_departure_time"] == departure["expected_departure_time"]:
                train = "On time"

        w, _, bitmap = cachedBitmapText(train, font)
        draw.bitmap((width - w, 0), bitmap, fill="yellow")
    return drawText

def renderPlatform(departure):
    def drawText(draw, *_):
        if "platform" in departure:
            platform = "Plat " + departure["platform"]
            if departure["platform"].lower() == "bus":
                platform = "BUS"
            _, _, bitmap = cachedBitmapText(platform, font)
            draw.bitmap((0, 0), bitmap, fill="yellow")
    return drawText

def renderCallingAt(draw, *_):
    stations = "Calling at: "
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

def renderStations(stations):
    def drawText(draw, *_):
        global stationRenderCount, pauseCount, pixelsLeft, pixelsUp, hasElevated

        if len(stations) == stationRenderCount - 5:
            stationRenderCount = 0

        txt_width, txt_height, bitmap = cachedBitmapText(stations, font)

        if hasElevated:
            # slide the bitmap left until it's fully out of view
            draw.bitmap((pixelsLeft - 1, 0), bitmap, fill="yellow")
            if -pixelsLeft > txt_width and pauseCount < 8:
                pauseCount += 1
                pixelsLeft = 0
                hasElevated = 0
            else:
                pauseCount = 0
                pixelsLeft = pixelsLeft - 1
        else:
            # slide the bitmap up from the bottom of its viewport until it's fully in view
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

def renderPoweredBy(xOffset):
    def drawText(draw, *_):
        text = "Powered by"
        draw.text((int(xOffset), 0), text=text, font=fontBold, fill="yellow")

    return drawText


def renderNRE(xOffset):
    def drawText(draw, *_):
        text = "National Rail Enquiries"
        draw.text((int(xOffset), 0), text=text, font=fontBold, fill="yellow")

    return drawText


def renderName(xOffset):
    def drawText(draw, *_):
        text = "UK Train Departure Display"
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

def loadData(apiConfig, journeyConfig):
    runHours = [int(x) for x in apiConfig['operatingHours'].split('-')]
    if isRun(runHours[0], runHours[1]) == False:
        return False, False, journeyConfig['outOfHoursName']

    departures, stationName = loadDeparturesForStation(
        journeyConfig, apiConfig["apiKey"])

    if (departures == None):
        return False, False, stationName

    firstDepartureDestinations = departures[0]["calling_at_list"]
    return departures, firstDepartureDestinations, stationName


def drawStartup(device, width, height):
    virtualViewport = viewport(device, width=width, height=height)

    with canvas(device):
        nameSize = int(fontBold.getlength("UK Train Departure Display"))
        poweredSize = int(fontBold.getlength("Powered by"))
        NRESize = int(fontBold.getlength("National Rail Enquiries"))

        rowOne = snapshot(width, 10, renderName((width - nameSize) / 2), interval=10)
        rowThree = snapshot(width, 10, renderPoweredBy((width - poweredSize) / 2), interval=10)
        rowFour = snapshot(width, 10, renderNRE((width - NRESize) / 2), interval=10)

        if len(virtualViewport._hotspots) > 0:
            for hotspot, xy in virtualViewport._hotspots:
                virtualViewport.remove_hotspot(hotspot, xy)

        virtualViewport.add_hotspot(rowOne, (0, 0))
        virtualViewport.add_hotspot(rowThree, (0, 24))
        virtualViewport.add_hotspot(rowFour, (0, 36))

    return virtualViewport

def drawBlankSignage(device, width, height, departureStation):
    global stationRenderCount, pauseCount

    welcomeSize = int(fontBold.getlength("Welcome to"))
    stationSize = int(fontBold.getlength(departureStation))

    device.clear()

    virtualViewport = viewport(device, width=width, height=height)

    rowOne = snapshot(width, 10, renderWelcomeTo(
        (width - welcomeSize) / 2), interval=config["refreshTime"])
    rowTwo = snapshot(width, 10, renderDepartureStation(
        departureStation, (width - stationSize) / 2), interval=config["refreshTime"])
    rowThree = snapshot(width, 10, renderDots, interval=config["refreshTime"])
    # this will skip a second sometimes if set to 1, but a hotspot burns CPU
    # so set to snapshot of 0.1; you won't notice
    rowTime = snapshot(width, 14, renderTime, interval=0.1)

    if len(virtualViewport._hotspots) > 0:
        for vhotspot, xy in virtualViewport._hotspots:
            virtualViewport.remove_hotspot(vhotspot, xy)

    virtualViewport.add_hotspot(rowOne, (0, 0))
    virtualViewport.add_hotspot(rowTwo, (0, 12))
    virtualViewport.add_hotspot(rowThree, (0, 24))
    virtualViewport.add_hotspot(rowTime, (0, 50))

    return virtualViewport

def platform_filter(departureData, platformNumber, station):
    platformDepartures = []
    for sub in departureData:
        if platformNumber == "":
            platformDepartures.append(sub)
        elif sub.get('platform') is not None:
            if sub['platform'] == platformNumber:
                res = sub
                platformDepartures.append(res)

    if len(platformDepartures) > 0:
        firstDepartureDestinations = platformDepartures[0]["calling_at_list"]
        platformData = platformDepartures, firstDepartureDestinations, station
    else:
        platformData = platformDepartures, "", station

    return platformData

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

    def renderDepartureDetails(departure, font, pos):
        departureTime = departure["aimed_departure_time"]
        destinationName = departure["destination_name"]
        
        # Debug print statements
        print(f"Rendering departure details for {departureTime} to {destinationName}")

        def drawText(draw, *_):
            train = f"{departureTime}  {destinationName}"
            _, _, bitmap = cachedBitmapText(train, font)
            draw.bitmap((0, 0), bitmap, fill="yellow")

        return drawText

    def renderServiceAndCarriages(departure, font):
        serviceMessage = departure.get("service_message", "")
        carriagesMessage = departure.get("carriages_message", "")
        
        def drawText(draw, *_):
            y_offset = 0
            if serviceMessage:
                _, _, bitmap = cachedBitmapText(serviceMessage, font)
                draw.bitmap((0, y_offset), bitmap, fill="yellow")
                y_offset += 10
            if carriagesMessage:
                _, _, bitmap = cachedBitmapText(carriagesMessage, font)
                draw.bitmap((0, y_offset), bitmap, fill="yellow")
                y_offset += 10
        
        return drawText

    def renderStationsWithServiceAndCarriages(stations, departure):
        serviceMessage = departure.get("service_message", "")
        carriagesMessage = departure.get("carriages_message", "")
        
        def drawText(draw, *_):
            global stationRenderCount, pauseCount, pixelsLeft, pixelsUp, hasElevated

            if len(stations) == stationRenderCount - 5:
                stationRenderCount = 0

            stationsText = stations + " " + serviceMessage + " " + carriagesMessage
            txt_width, txt_height, bitmap = cachedBitmapText(stationsText, font)

            if hasElevated:
                # slide the bitmap left until it's fully out of view
                draw.bitmap((pixelsLeft - 1, 0), bitmap, fill="yellow")
                if -pixelsLeft > txt_width and pauseCount < 8:
                    pauseCount += 1
                    pixelsLeft = 0
                    hasElevated = 0
                else:
                    pauseCount = 0
                    pixelsLeft = pixelsLeft - 1
            else:
                # slide the bitmap up from the bottom of its viewport until it's fully in view
                draw.bitmap((0, txt_height - pixelsUp), bitmap, fill="yellow")
                if pixelsUp == txt_height:
                    pauseCount += 1
                    if pauseCount > 20:
                        hasElevated = 1
                        pixelsUp = 0
                else:
                    pixelsUp = pixelsUp + 1
        
        return drawText
    
    rowOneA = snapshot(width - w - pw - 5, 10, renderDepartureDetails(departures[0], firstFont, '1st'), interval=10)
    rowOneB = snapshot(w, 10, renderServiceStatus(departures[0]), interval=10)
    rowOneC = snapshot(pw, 10, renderPlatform(departures[0]), interval=10)
    rowTwoA = snapshot(callingWidth, 10, renderCallingAt, interval=100)
    rowTwoB = snapshot(width - callingWidth, 10, renderStationsWithServiceAndCarriages(firstDepartureDestinations, departures[0]), interval=0.02)
    
    if len(departures) > 1:
        rowThreeA = snapshot(width - w - pw, 10, renderDepartureDetails(departures[1], font, '2nd'), interval=10)
        rowThreeB = snapshot(w, 10, renderServiceStatus(departures[1]), interval=10)
        rowThreeC = snapshot(pw, 10, renderPlatform(departures[1]), interval=10)
    if len(departures) > 2:
        rowFourA = snapshot(width - w - pw, 10, renderDepartureDetails(departures[2], font, '3rd'), interval=10)
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

    data = loadData(config["transportApi"], config["journey"])

    if data[0] == False:
        virtual = drawBlankSignage(
            device, width=widgetWidth, height=widgetHeight, departureStation=data[2])
    else:
        virtual = drawSignage(device, width=widgetWidth,
                              height=widgetHeight, data=data)

    timeAtStart = time.time()
    timeNow = time.time()

    while True:
        if(timeNow - timeAtStart >= config["refreshTime"]):
            # display NRE attribution while data loads
            virtual = drawStartup(device, width=widgetWidth, height=widgetHeight)
            virtual.refresh()

            data = loadData(config["transportApi"], config["journey"])
            if data[0] == False:
                virtual = drawBlankSignage(
                    device, width=widgetWidth, height=widgetHeight, departureStation=data[2])
            else:
                virtual = drawSignage(device, width=widgetWidth, height=widgetHeight, data=data)

            timeAtStart = time.time()

        timeNow = time.time()
        virtual.refresh()

except KeyboardInterrupt:
    pass
except ValueError as err:
    print(f"Error: {err}")
