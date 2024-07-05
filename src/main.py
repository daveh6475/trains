import os
import time
import json
import requests
import base64
import cProfile
import pstats
import io

from datetime import datetime, date
from PIL import ImageFont, ImageDraw, Image
from PIL.ImageFont import FreeTypeFont
from helpers import get_device
from trains import loadDeparturesForStationRTT, loadDestinationsForDepartureRTT, CallingPoints
from luma.core.render import canvas
from luma.core.virtual import viewport, snapshot
from open import isRun
from typing import Any, List, Tuple, Dict

DISPLAY_WIDTH = 256
DISPLAY_HEIGHT = 64

def loadConfig() -> Dict[str, Any]:
    with open('config.json', 'r') as jsonConfig:
        return json.load(jsonConfig)

def makeFont(name: str, size: int) -> FreeTypeFont:
    font_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'fonts', name))
    return ImageFont.truetype(font_path, size)

def format_hhmm(timestamp: str) -> str:
    return f"{timestamp[0:2]}:{timestamp[2:4]}"

def renderDestination(departure: Dict[str, Any], font: FreeTypeFont, n: int = 0):
    departureTime = departure['departureTime']
    destinationName = departure['destination']
    ordinal = ["", "1st ", "2nd ", "3rd ", "4th "][n]

    def drawText(draw, width: int, height: int):
        train = f"{ordinal}{departureTime}  {destinationName}"
        draw.text((0, 0), text=train, font=font, fill="yellow")

    return drawText

def renderServiceStatus(departure: Dict[str, Any]):
    def drawText(draw, width: int, height: int):
        train = "Cancelled" if departure['isCancelled'] else f"Exp {departure['departureTime']}"
        w = int(draw.textlength(train, font))
        draw.text((width - w, 0), text=train, font=font, fill="yellow")

    return drawText

def renderPlatform(departure: Dict[str, Any]):
    def drawText(draw, width: int, height: int):
        if not departure['isCancelled'] and isinstance(departure['platform'], str):
            draw.text((0, 0), text="Plat " + departure['platform'], font=font, fill="yellow")

    return drawText

def renderCallingAt(draw, width: int, height: int):
    draw.text((0, 0), text="Calling at:", font=font, fill="yellow")

def get_stations_string(stations: List[CallingPoints], toc: str) -> str:
    if not stations:
        return "No calling points available."

    calling_at_str = ", ".join([f"{call.station} ({format_hhmm(call.arrival_time)})" for call in stations[:-1]])
    if len(stations) > 1:
        calling_at_str += f" and {stations[-1].station} ({format_hhmm(stations[-1].arrival_time)})."
    else:
        calling_at_str = f"{stations[0].station} ({format_hhmm(stations[0].arrival_time)}) only."

    calling_at_str += f"    (A {toc} service.)"
    return calling_at_str

def renderStations(stations: List[CallingPoints], toc: str):
    calling_at_str = get_stations_string(stations, toc)

    def drawText(draw, width: int, height: int):
        global stationRenderCount, pauseCount

        calling_at_len = int(draw.textlength(calling_at_str, font))
        if calling_at_len == -stationRenderCount - 5:
            stationRenderCount = 0

        draw.text((stationRenderCount, 0), text=calling_at_str, font=font, fill="yellow")

        if stationRenderCount == 0 and pauseCount < 25:
            pauseCount += 1
        else:
            pauseCount = 0
            stationRenderCount -= 1

    return drawText

def renderTime(draw, width: int, height: int):
    rawTime = datetime.now().time()
    hour, minute, second = str(rawTime).split('.')[0].split(':')

    w1 = int(draw.textlength(f"{hour}:{minute}", fontBoldLarge))
    w2 = int(draw.textlength(":00", fontBoldTall))

    draw.text(((width - w1 - w2) / 2, 0), text=f"{hour}:{minute}", font=fontBoldLarge, fill="yellow")
    draw.text((((width - w1 - w2) / 2) + w1, 5), text=f":{second}", font=fontBoldTall, fill="yellow")

def renderWelcomeTo(xOffset: int):
    def drawText(draw, width: int, height: int):
        draw.text((int(xOffset), 0), text="Welcome to", font=fontBold, fill="yellow")

    return drawText

def renderDepartureStation(departureStation: str, xOffset: int):
    def draw(draw, width: int, height: int):
        draw.text((int(xOffset), 0), text=departureStation, font=fontBold, fill="yellow")

    return draw

def renderDots(draw, width: int, height: int):
    draw.text((0, 0), text=".  .  .", font=fontBold, fill="yellow")

def loadDeparturesForStationRTT(journeyConfig: Dict[str, Any], username: str, password: str) -> Tuple[List[Dict[str, Any]], str]:
    if not journeyConfig.get("departureStation"):
        raise ValueError("Please set the journey.departureStation property in config.json")

    if not username or not password:
        raise ValueError("Please complete the rttApi section of your config.json file")

    departureStation = journeyConfig["departureStation"]

    response = requests.get(f"https://api.rtt.io/api/v1/json/search/{departureStation}", auth=(username, password))
    response.raise_for_status()
    data = response.json()
    translated_departures = []
    td = date.today()

    if not data.get('services'):
        return translated_departures, departureStation

    for item in data['services'][:5]:
        uid = item['serviceUid']
        destination_name = abbrStation(journeyConfig, item['locationDetail']['destination'][0]['description'])

        dt = item['locationDetail']['gbttBookedDeparture']
        edt = item['locationDetail'].get('realtimeDeparture', dt)

        aimed_departure_time = f"{dt[:2]}:{dt[2:]}"
        expected_departure_time = f"{edt[:2]}:{edt[2:]}"
        status = item['locationDetail']['displayAs']
        mode = item['serviceType']
        platform = item['locationDetail'].get('platform', "")

        timetable_url = f"https://api.rtt.io/api/v1/json/service/{uid}/{td.year}/{td.month:02}/{td.day:02}"
        calling_at = loadDestinationsForDepartureRTT(journeyConfig, username, password, timetable_url)

        translated_departures.append({
            'uid': uid,
            'destination_name': destination_name,
            'aimed_departure_time': aimed_departure_time,
            'expected_departure_time': expected_departure_time,
            'status': status,
            'mode': mode,
            'platform': platform,
            'calling_at': calling_at
        })

    return translated_departures, departureStation

def loadDestinationsForDepartureRTT(journeyConfig: Dict[str, Any], username: str, password: str, timetableUrl: str) -> List[str]:
    response = requests.get(timetableUrl, auth=(username, password))
    response.raise_for_status()
    calling_data = response.json()

    index = next((i for i, loc in enumerate(calling_data['locations']) if loc['crs'] == journeyConfig["departureStation"]), -1)
    calling_at = [abbrStation(journeyConfig, loc['description']) for loc in calling_data['locations'][index+1:]]

    if len(calling_at) == 1:
        calling_at[0] += ' only.'

    return calling_at

def drawBlankSignage(device, width: int, height: int, departureStation: str):
    global stationRenderCount, pauseCount

    with canvas(device) as draw:
        welcome_bbox = draw.textbbox((0, 0), "Welcome to", fontBold)
        welcomeSizeX = welcome_bbox[2] - welcome_bbox[0]

    with canvas(device) as draw:
        station_bbox = draw.textbbox((0, 0), departureStation, fontBold)
        stationSizeX = station_bbox[2] - station_bbox[0]

    device.clear()

    virtualViewport = viewport(device, width=width, height=height)

    rowOne = snapshot(width, 10, renderWelcomeTo((width - welcomeSizeX) / 2), interval=10)
    rowTwo = snapshot(width, 10, renderDepartureStation(departureStation, (width - stationSizeX) / 2), interval=10)
    rowThree = snapshot(width, 10, renderDots, interval=10)
    rowTime = snapshot(width, 14, renderTime, interval=1)

    if virtualViewport._hotspots:
        for hotspot, xy in virtualViewport._hotspots:
            virtualViewport.remove_hotspot(hotspot, xy)

    virtualViewport.add_hotspot(rowOne, (0, 0))
    virtualViewport.add_hotspot(rowTwo, (0, 12))
    virtualViewport.add_hotspot(rowThree, (0, 24))
    virtualViewport.add_hotspot(rowTime, (0, 50))

    return virtualViewport

def drawSignage(device, width, height, data):
    global stationRenderCount, pauseCount

    device.clear()

    virtualViewport = viewport(device, width=width, height=height)

    status = "Exp 00:00"
    callingAt = "Calling at:"

    departures, firstDepartureDestinations, departureStation = data

    with canvas(device) as draw:
        calling_bbox = draw.textbbox((0, 0), callingAt, font)
        callingWidth = calling_bbox[2] - calling_bbox[0]

    width = virtualViewport.width

    with canvas(device) as draw:
        status_bbox = draw.textbbox((0, 0), status, font)
        w = status_bbox[2] - status_bbox[0]
        platform_bbox = draw.textbbox((0, 0), "Plat 88", font)
        pw = platform_bbox[2] - platform_bbox[0]

    rowOneA = snapshot(width - w - pw, 10, renderDestination(departures[0], fontBold), interval=10)
    rowOneB = snapshot(w, 10, renderServiceStatus(departures[0]), interval=1)
    rowOneC = snapshot(pw, 10, renderPlatform(departures[0]), interval=10)
    rowTwoA = snapshot(callingWidth, 10, renderCallingAt, interval=100)
    rowTwoB = snapshot(width - callingWidth, 10, renderStations(firstDepartureDestinations, departures[0]['atocName']), interval=0.1)
    if len(departures) > 1:
        rowThreeA = snapshot(width - w - pw, 10, renderDestination(departures[1], font), interval=10)
        rowThreeB = snapshot(w, 10, renderServiceStatus(departures[1]), interval=1)
        rowThreeC = snapshot(pw, 10, renderPlatform(departures[1]), interval=10)

    if len(departures) > 2:
        rowFourA = snapshot(width - w - pw, 10, renderDestination(departures[2], font), interval=10)
        rowFourB = snapshot(w, 10, renderServiceStatus(departures[2]), interval=1)
        rowFourC = snapshot(pw, 10, renderPlatform(departures[2]), interval=10)

    rowTime = snapshot(width, 14, renderTime, interval=1)

    if virtualViewport._hotspots:
        for hotspot, xy in virtualViewport._hotspots:
            virtualViewport.remove_hotspot(hotspot, xy)

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
    config = loadConfig()

    device = get_device()
    font = makeFont("Dot Matrix Regular.ttf", 10)
    fontBold = makeFont("Dot Matrix Bold.ttf", 10)
    fontBoldTall = makeFont("Dot Matrix Bold Tall.ttf", 10)
    fontBoldLarge = makeFont("Dot Matrix Bold.ttf", 20)

    stationRenderCount = 0
    pauseCount = 0
    loop_count = 0

    if config["apiMethod"] == 'rtt':
        data = loadDataRTT(config["rttApi"], config["journey"])
    else:
        raise Exception(f"Unsupported apiMethod: {config['apiMethod']}")

    if not data[0]:
        virtual = drawBlankSignage(device, width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT, departureStation=data[2])
    else:
        virtual = drawSignage(device, width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT, data=data)

    timeAtStart = time.time()
    timeNow = time.time()

    while True:
        if timeNow - timeAtStart >= config["refreshTime"]:
            if config["apiMethod"] == 'rtt':
                data = loadDataRTT(config["rttApi"], config["journey"])

            if not data[0]:
                virtual = drawBlankSignage(device, width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT, departureStation=data[2])
            else:
                virtual = drawSignage(device, width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT, data=data)

            timeAtStart = time.time()

        timeNow = time.time()
        virtual.refresh()

except KeyboardInterrupt:
    pass
except ValueError as err:
    print(f"Error: {err}")
except requests.RequestException as err:
    print(f"Request Error: {err}")

def main():
    device = get_device()
    width, height = device.width, device.height
    
    config = loadConfig()
    rttApi = config['rttApi']
    journey = config['journey']
    
    data = loadDataRTT(rttApi, journey)
    if data:
        drawSignage(device, width, height, data)

if __name__ == '__main__':
    pr = cProfile.Profile()
    pr.enable()
    main()
    pr.disable()
    
    s = io.StringIO()
    sortby = 'cumulative'
    ps = pstats.Stats(pr, stream=s).sort_stats(sortby)
    ps.print_stats()
    print(s.getvalue())
