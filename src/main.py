import os
import sys
import time
import json
import requests
import base64
import cProfile
import pstats
import io

from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from PIL.ImageFont import FreeTypeFont
from helpers import get_device, AnimatedObject, RenderText, Animation, AnimationSequence, move_object, scroll_left, scroll_up, ObjectRow, reset_object
from trains import loadDeparturesForStationRTT, loadDestinationsForDepartureRTT, ProcessedDepartures, CallingPoints
from luma.core.render import canvas
from luma.core.virtual import viewport, snapshot
from open import isRun
from typing import Any, Dict, List, Tuple

DISPLAY_WIDTH = 256
DISPLAY_HEIGHT = 64

def loadConfig() -> Dict[str, Any]:
    with open('config.json', 'r') as jsonConfig:
        data = json.load(jsonConfig)
        return data

def makeFont(name: str, size: int) -> FreeTypeFont:
    font_path = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            'fonts',
            name
        )
    )
    return ImageFont.truetype(font_path, size)

def format_hhmm(timestamp: str) -> str:
    return f"{timestamp[0:2]}:{timestamp[2:4]}"

def renderText(draw, width: int, height: int, text: str, font: FreeTypeFont, position: Tuple[int, int]):
    draw.text(position, text=text, font=font, fill="yellow")

def renderDestination(departure: Dict[str, Any], font: FreeTypeFont, n: int = 0):
    departureTime = departure['departureTime']
    destinationName = departure['destination']

    def drawText(draw, width: int, height: int):
        ordinal = ""
        if n == 1:
            ordinal = "1st "
        elif n == 2:
            ordinal = "2nd "
        elif n == 3:
            ordinal = "3rd "
        elif n == 4:
            ordinal = "4th "

        train = f"{ordinal}{departureTime}  {destinationName}"
        renderText(draw, width, height, train, font, (0, 0))

    return drawText

def renderServiceStatus(departure: Dict[str, Any], font: FreeTypeFont):
    def drawText(draw, width: int, height: int):
        train = ""

        if departure['isCancelled']:
            train = "Cancelled"
        else:
            train = 'Exp ' + departure['departureTime']

        w = int(draw.textlength(train, font))
        renderText(draw, width, height, train, font, (width - w, 0))

    return drawText

def renderPlatform(departure: Dict[str, Any], font: FreeTypeFont):
    def drawText(draw, width: int, height: int):
        if not departure['isCancelled']:
            if isinstance(departure['platform'], str):
                renderText(draw, width, height, "Plat " + departure['platform'], font, (0, 0))
    return drawText

def renderCallingAt(draw, width: int, height: int, font: FreeTypeFont):
    renderText(draw, width, height, "Calling at:", font, (0, 0))

def get_stations_string(stations: List[CallingPoints], toc: str) -> str:
    if not stations:  # Check if stations list is empty
        return "No calling points available."

    if len(stations) == 1:
        calling_at_str = f"{stations[0].station} ({format_hhmm(stations[0].arrival_time)}) only."
    else:
        calling_at_str = ", ".join([f"{call.station} ({format_hhmm(call.arrival_time)})" for call in stations[:-1]])
        calling_at_str += f" and {stations[-1].station} ({format_hhmm(stations[-1].arrival_time)})."

    calling_at_str += f"    (A {toc} service.)"
    return calling_at_str

def renderStations(stations: List[CallingPoints], toc: str, font: FreeTypeFont):
    calling_at_str = get_stations_string(stations, toc)

    def drawText(draw, width: int, height: int):
        global stationRenderCount, pauseCount

        calling_at_len = int(draw.textlength(calling_at_str, font))

        if calling_at_len == -stationRenderCount - 5:
            stationRenderCount = 0

        renderText(draw, width, height, calling_at_str, font, (stationRenderCount, 0))

        if stationRenderCount == 0 and pauseCount < 25:
            pauseCount += 1
            stationRenderCount = 0
        else:
            pauseCount = 0
            stationRenderCount -= 1

    return drawText

def renderTime(draw, width: int, height: int, fontBoldLarge: FreeTypeFont, fontBoldTall: FreeTypeFont):
    rawTime = datetime.now().time()
    hour, minute, second = str(rawTime).split('.')[0].split(':')

    w1 = int(draw.textlength("{}:{}".format(hour, minute), fontBoldLarge))
    w2 = int(draw.textlength(":00", fontBoldTall))

    renderText(draw, width, height, "{}:{}".format(hour, minute), fontBoldLarge, ((width - w1 - w2) / 2, 0))
    renderText(draw, width, height, ":{}".format(second), fontBoldTall, (((width - w1 - w2) / 2) + w1, 5))

def renderWelcomeTo(xOffset: int, fontBold: FreeTypeFont):
    def drawText(draw, width: int, height: int):
        renderText(draw, width, height, "Welcome to", fontBold, (int(xOffset), 0))

    return drawText

def renderDepartureStation(departureStation: str, xOffset: int, fontBold: FreeTypeFont):
    def draw(draw, width: int, height: int):
        renderText(draw, width, height, departureStation, fontBold, (int(xOffset), 0))

    return draw

def renderDots(draw, width: int, height: int, fontBold: FreeTypeFont):
    renderText(draw, width, height, ".  .  .", fontBold, (0, 0))

def loadDataRTT(apiDetails: Dict[str, Any], journey: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[CallingPoints], str]:
    base_url = "https://api.rtt.io/api/v1/json/search/"
    details_base_url = "https://api.rtt.io/api/v1/json/service/"
    credentials = f"{apiDetails['username']}:{apiDetails['password']}"
    encoded_credentials = base64.b64encode(credentials.encode()).decode()

    headers = {'Authorization': f"Basic {encoded_credentials}"}

    url = f"{base_url}{journey['departureStation']}"
    departure_response = requests.get(url, headers=headers)
    departure_response.raise_for_status()
    departures_data = departure_response.json()

    departures = []
    for service in departures_data.get('services', []):
        origin_info = service.get('origin', [{}])[0]
        destination_info = service['locationDetail'].get('destination', [{}])[0]

        departures.append({
            'serviceUid': service['serviceUid'],
            'runDate': service['runDate'],
            'trainIdentity': service['trainIdentity'],
            'origin': origin_info.get('description', 'Unknown Origin'),
            'destination': destination_info.get('description', 'Unknown Destination'),
            'departureTime': service['locationDetail'].get('gbttBookedDeparture', 'Unknown Time'),
            'arrivalTime': destination_info.get('publicTime', 'Unknown Time'),
            'platform': service['locationDetail'].get('platform', 'N/A'),
            'isCancelled': service['locationDetail'].get('displayAs', '') == 'CANCELLED_CALL',
            'atocName': service.get('atocName', 'Unknown TOC')
        })

    first_departure_destinations = []
    if departures:
        first_departure_date = datetime.strptime(departures[0]['runDate'], "%Y-%m-%d").strftime("%Y/%m/%d")
        first_departure_url = f"{details_base_url}{departures[0]['serviceUid']}/{first_departure_date}"
        first_departure_response = requests.get(first_departure_url, headers=headers)
        if first_departure_response.status_code == 200:
            first_departure_data = first_departure_response.json()
            start_index = next((index for index, loc in enumerate(first_departure_data.get('locations', [])) if loc['crs'] == journey['departureStation']), None)

            if start_index is not None:
                for location in first_departure_data['locations'][start_index+1:]:
                    first_departure_destinations.append(
                        CallingPoints(
                            station=location['description'],
                            arrival_time=location.get('gbttBookedArrival', 'Unknown')
                        )
                    )
    else:
        first_departure_destinations = []

    return departures, first_departure_destinations, journey['departureStation']

def drawBlankSignage(device, width: int, height: int, departureStation: str, fontBold: FreeTypeFont, fontBoldLarge: FreeTypeFont):
    global stationRenderCount, pauseCount

    with canvas(device) as draw:
        welcome_bbox = draw.textbbox((0, 0), "Welcome to", fontBold)
        welcomeSizeX = welcome_bbox[2] - welcome_bbox[0]

    with canvas(device) as draw:
        station_bbox = draw.textbbox((0, 0), departureStation, fontBold)
        stationSizeX = station_bbox[2] - station_bbox[0]

    device.clear()

    virtualViewport = viewport(device, width=width, height=height)

    rowOne = snapshot(width, 10, renderWelcomeTo(
        int((width - welcomeSizeX) / 2), fontBold), interval=10)
    rowTwo = snapshot(width, 10, renderDepartureStation(
        departureStation, int((width - stationSizeX) / 2), fontBold), interval=10)
    rowThree = snapshot(width, 10, renderDots, interval=10, fontBold=fontBold)
    rowTime = snapshot(width, 14, renderTime, interval=1, fontBoldLarge=fontBoldLarge, fontBoldTall=fontBoldTall)

    if len(virtualViewport._hotspots) > 0:
        for hotspot, xy in virtualViewport._hotspots:
            virtualViewport.remove_hotspot(hotspot, xy)

    virtualViewport.add_hotspot(rowOne, (0, 0))
    virtualViewport.add_hotspot(rowTwo, (0, 12))
    virtualViewport.add_hotspot(rowThree, (0, 24))
    virtualViewport.add_hotspot(rowTime, (0, 50))

    return virtualViewport

def drawSignage(device, width: int, height: int, data: Tuple[List[Dict[str, Any]], List[CallingPoints], str], font: FreeTypeFont, fontBold: FreeTypeFont, fontBoldLarge: FreeTypeFont, fontBoldTall: FreeTypeFont):
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

    rowOneA = snapshot(
        width - w - pw, 10, renderDestination(departures[0], fontBold), interval=10)
    rowOneB = snapshot(w, 10, renderServiceStatus(
        departures[0], font), interval=1)
    rowOneC = snapshot(pw, 10, renderPlatform(departures[0], font), interval=10)
    rowTwoA = snapshot(callingWidth, 10, renderCallingAt, interval=100, font=font)
    rowTwoB = snapshot(width - callingWidth, 10,
                       renderStations(firstDepartureDestinations, departures[0]['atocName'], font), interval=0.1)
    if len(departures) > 1:
        rowThreeA = snapshot(width - w - pw, 10, renderDestination(
            departures[1], font), interval=10)
        rowThreeB = snapshot(w, 10, renderServiceStatus(
            departures[1], font), interval=1)
        rowThreeC = snapshot(pw, 10, renderPlatform(departures[1], font), interval=10)

    if len(departures) > 2:
        rowFourA = snapshot(width - w - pw, 10, renderDestination(
            departures[2], font), interval=10)
        rowFourB = snapshot(w, 10, renderServiceStatus(
            departures[2], font), interval=1)
        rowFourC = snapshot(pw, 10, renderPlatform(departures[2], font), interval=10)

    rowTime = snapshot(width, 14, renderTime, interval=1, fontBoldLarge=fontBoldLarge, fontBoldTall=fontBoldTall)

    if len(virtualViewport._hotspots) > 0:
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

def main():
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

    if len(data[0]) == 0:
        virtual = drawBlankSignage(
            device, width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT, departureStation=data[2], fontBold=fontBold, fontBoldLarge=fontBoldLarge)
    else:
        virtual = drawSignage(device, width=DISPLAY_WIDTH,
                              height=DISPLAY_HEIGHT, data=data, font=font, fontBold=fontBold, fontBoldLarge=fontBoldLarge, fontBoldTall=fontBoldTall)

    timeAtStart = time.time()
    timeNow = time.time()

    while True:
        if (timeNow - timeAtStart >= config["refreshTime"]):
            if config["apiMethod"] == 'rtt':
                data = loadDataRTT(config["rttApi"], config["journey"])

            if len(data[0]) == 0:
                virtual = drawBlankSignage(
                    device, width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT, departureStation=data[2], fontBold=fontBold, fontBoldLarge=fontBoldLarge)
            else:
                virtual = drawSignage(device, width=DISPLAY_WIDTH,
                                      height=DISPLAY_HEIGHT, data=data, font=font, fontBold=fontBold, fontBoldLarge=fontBoldLarge, fontBoldTall=fontBoldTall)

            timeAtStart = time.time()

        timeNow = time.time()
        virtual.refresh()

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
