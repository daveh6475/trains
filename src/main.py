import os
import sys
import time
import json

from datetime import datetime
from PIL import ImageFont, Image
from PIL.ImageFont import FreeTypeFont
from helpers import get_device, AnimatedObject, RenderText, Animation, AnimationSequence, move_object, scroll_left, scroll_up, ObjectRow, reset_object
from trains import loadDeparturesForStationRTT, loadDestinationsForDepartureRTT, ProcessedDepartures, CallingPoints
from luma.core.render import canvas
from luma.core.virtual import viewport, snapshot
from open import isRun
from typing import Any

DISPLAY_WIDTH = 256
DISPLAY_HEIGHT = 64

def loadConfig() -> dict[str, Any]:
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


def renderDestination(departure: ProcessedDepartures, font: FreeTypeFont, n: int = 0):
    departureTime = departure.aimed_departure_time
    destinationName = departure.destination_name

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
        draw.text((0, 0), text=train, font=font, fill="yellow")

    return drawText


def renderServiceStatus(departure: ProcessedDepartures):
    def drawText(draw, width: int, height: int):
        train = ""

        if departure.status == "CANCELLED" or departure.status == "CANCELLED_CALL" or departure.status == "CANCELLED_PASS":
            train = "Cancelled"
        else:
            if isinstance(departure.expected_departure_time, str):
                train = 'Exp '+ departure.expected_departure_time

            if departure.expected_departure_time == departure.expected_departure_time:
                train = "On time"

        w = int(draw.textlength(train, font))
        draw.text((width-w,0), text=train, font=font, fill="yellow")
    return drawText

def renderPlatform(departure: ProcessedDepartures):
    def drawText(draw, width: int, height: int):
        if departure.mode == "bus":
            draw.text((0, 0), text="BUS", font=font, fill="yellow")
        else:
            if isinstance(departure.platform, str):
                draw.text((0, 0), text="Plat " + departure.platform, font=font, fill="yellow")
    return drawText

def renderCallingAt(draw, width: int, height: int):
    stations = "Calling at:"
    draw.text((0, 0), text=stations, font=font, fill="yellow")

def get_stations_string(stations: list[CallingPoints], toc: str) -> str:
    if len(stations) == 1:
         calling_at_str = f"{stations[0].station} ({format_hhmm(stations[0].arrival_time)}) only."
        
    else:
        calling_at_str = ", ".join([f"{call.station} ({format_hhmm(call.arrival_time)})" for call in stations[:-1]])
        calling_at_str += f" and {stations[-1].station} ({format_hhmm(stations[-1].arrival_time)})."

    calling_at_str += f"    (A {toc} service.)"

    return calling_at_str

def renderStations(stations: list[CallingPoints], toc: str):

    if len(stations) == 1:
         calling_at_str = f"{stations[0].station} ({format_hhmm(stations[0].arrival_time)}) only."
        
    else:
        calling_at_str = ", ".join([f"{call.station} ({format_hhmm(call.arrival_time)})" for call in stations[:-1]])
        calling_at_str += f" and {stations[-1].station} ({format_hhmm(stations[-1].arrival_time)})."

    calling_at_str += f"    (A {toc} service.)"

    def drawText(draw, width: int, height: int):
        global stationRenderCount, pauseCount

        calling_at_len = int(draw.textlength(calling_at_str, font))

        if calling_at_len == -stationRenderCount - 5:
            stationRenderCount = 0

        draw.text((stationRenderCount, 0), text=calling_at_str, font=font, fill="yellow")

        if stationRenderCount == 0 and pauseCount < 25:
            pauseCount += 1
            stationRenderCount = 0
        else:
            pauseCount = 0
            stationRenderCount -= 1

    return drawText

def renderTime(draw, width: int, height: int):
    rawTime = datetime.now().time()
    hour, minute, second = str(rawTime).split('.')[0].split(':')

    w1 = int(draw.textlength("{}:{}".format(hour, minute), fontBoldLarge))
    w2 = int(draw.textlength(":00", fontBoldTall))

    draw.text(((width - w1 - w2) / 2, 0), text="{}:{}".format(hour, minute),
              font=fontBoldLarge, fill="yellow")
    draw.text((((width - w1 -w2) / 2) + w1, 5), text=":{}".format(second),
              font=fontBoldTall, fill="yellow")


def renderWelcomeTo(xOffset: int):
    def drawText(draw, width: int, height: int):
        text = "Welcome to"
        draw.text((int(xOffset), 0), text=text, font=fontBold, fill="yellow")

    return drawText


def renderDepartureStation(departureStation: str, xOffset: int):
    def draw(draw, width: int, height: int):
        text = departureStation
        draw.text((int(xOffset), 0), text=text, font=fontBold, fill="yellow")

    return draw


def renderDots(draw, width: int, height: int):
    text = ".  .  ."
    draw.text((0, 0), text=text, font=fontBold, fill="yellow")


def loadDataRTT(apiConfig: dict[str, Any], journeyConfig: dict[str, Any]) -> tuple[list[ProcessedDepartures], list[CallingPoints], str]:
    runHours = [int(x) for x in apiConfig['operatingHours'].split('-')]
    if isRun(runHours[0], runHours[1]) == False:
        print("Out of operating hours.")
        return [], [], journeyConfig['outOfHoursName']

    print("Loading departures for station...")
    departures, stationName = loadDeparturesForStationRTT(
        journeyConfig, apiConfig["username"], apiConfig["password"])

    if len(departures) == 0:
        print("No departures found.")
        return [], [], journeyConfig['outOfHoursName']

    print(f"Found {len(departures)} departures.")
    print(f"Loading destinations for the first departure with UID {departures[0].uid}...")

    firstDepartureDestinations = loadDestinationsForDepartureRTT(
        journeyConfig, apiConfig["username"], apiConfig["password"], departures[0].timetable_url)    

    print(f"Found {len(firstDepartureDestinations)} calling points for the first departure.")

    #return False, False, journeyConfig['outOfHoursName']
    return departures, firstDepartureDestinations, stationName

def drawBlankSignage(device, width: int, height: int, departureStation: str):
    global stationRenderCount, pauseCount

    with canvas(device) as draw:
        welcomeSizeX = int(draw.textlength("Welcome to", fontBold))

    with canvas(device) as draw:
        stationSizeX = int(draw.textlength(departureStation, fontBold))

    device.clear()

    virtualViewport = viewport(device, width=width, height=height)

    rowOne = snapshot(width, 10, renderWelcomeTo(
        int((width - welcomeSizeX) / 2)), interval=10)
    rowTwo = snapshot(width, 10, renderDepartureStation(
        departureStation, int((width - stationSizeX) / 2)), interval=10)
    rowThree = snapshot(width, 10, renderDots, interval=10)
    rowTime = snapshot(width, 14, renderTime, interval=1)

    if len(virtualViewport._hotspots) > 0:
        for hotspot, xy in virtualViewport._hotspots:
            virtualViewport.remove_hotspot(hotspot, xy)

    virtualViewport.add_hotspot(rowOne, (0, 0))
    virtualViewport.add_hotspot(rowTwo, (0, 12))
    virtualViewport.add_hotspot(rowThree, (0, 24))
    virtualViewport.add_hotspot(rowTime, (0, 50))

    return virtualViewport


def drawSignage(device, width: int, height: int, data: tuple[list[ProcessedDepartures], list[CallingPoints], str]):
    global stationRenderCount, pauseCount

    device.clear()

    virtualViewport = viewport(device, width=width, height=height)

    status = "Exp 00:00"
    callingAt = "Calling at: "

    departures, firstDepartureDestinations, departureStation = data

    with canvas(device) as draw:
        w = int(draw.textlength(callingAt, font))

    callingWidth = w
    width = virtualViewport.width

    # First measure the text size
    with canvas(device) as draw:
        w = int(draw.textlength(status, font))
        pw = int(draw.textlength("Plat 88", font))
    
    rowOneA = snapshot(
        width - w - pw, 10, renderDestination(departures[0], fontBold), interval=10)
    rowOneB = snapshot(w, 10, renderServiceStatus(
        departures[0]), interval=1)
    rowOneC = snapshot(pw, 10, renderPlatform(departures[0]), interval=10)
    rowTwoA = snapshot(callingWidth, 10, renderCallingAt, interval=100)
    rowTwoB = snapshot(width - callingWidth, 10,
                       renderStations(firstDepartureDestinations, departures[0].toc), interval=0.02)
    if(len(departures) > 1):
        rowThreeA = snapshot(width - w - pw, 10, renderDestination(
            departures[1], font, n=2), interval=10)
        rowThreeB = snapshot(w, 10, renderServiceStatus(
            departures[1]), interval=1)
        rowThreeC = snapshot(pw, 10, renderPlatform(departures[1]), interval=10)

    if(len(departures) > 2):
        rowFourA = snapshot(width - w - pw, 10, renderDestination(
            departures[2], font, n=3), interval=10)
        rowFourB = snapshot(w, 10, renderServiceStatus(
            departures[2]), interval=1)
        rowFourC = snapshot(pw, 10, renderPlatform(departures[2]), interval=10)

    rowTime = snapshot(width, 14, renderTime, interval=1)

    if len(virtualViewport._hotspots) > 0:
        for hotspot, xy in virtualViewport._hotspots:
            virtualViewport.remove_hotspot(hotspot, xy)

    stationRenderCount = 0
    pauseCount = 0

    virtualViewport.add_hotspot(rowOneA, (0, 0))
    virtualViewport.add_hotspot(rowOneB, (width - w, 0))
    virtualViewport.add_hotspot(rowOneC, (width - w - pw, 0))
    # virtualViewport.add_hotspot(rowTwoA, (0, 12))


    ca = AnimatedObject(device, (0, 12), [RenderText(text="Calling at: ", font=font)])

    # virtualViewport.add_hotspot(rowTwoB, (callingWidth, 12))
    stops = AnimatedObject(device, (callingWidth, 12), [RenderText(text=get_stations_string(firstDepartureDestinations, departures[0].toc), font=font)])
    stops.add_animations(
        AnimationSequence(
            sequence=[
                scroll_left(stops, delay=40),
                Animation(
                    obj_start=(stops.start_pos[0], stops.start_pos[1] + stops.height), obj_end=stops.start_pos,
                    viewport_start=(0, 0), viewport_end=(0, 0)),
                reset_object(stops)
            ],
            interval=0.02
        )
    )

    animated_row_two = ObjectRow(
        [ca, stops], DISPLAY_WIDTH
    )
    animated_row_two.add_hotspots(12, virtualViewport)


    if(len(departures) > 1):
        virtualViewport.add_hotspot(rowThreeA, (0, 24))
        virtualViewport.add_hotspot(rowThreeB, (width - w, 24))
        virtualViewport.add_hotspot(rowThreeC, (width - w - pw, 24))
    if(len(departures) > 2):
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
    # else:
    #     data = loadData(config["transportApi"], config["journey"])      
    else:
        raise Exception(f"Unsupported apiMethod: {config['apiMethod']}")

    if len(data[0]) == 0:
        virtual = drawBlankSignage(
            device, width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT, departureStation=data[2])
    else:
        virtual = drawSignage(device, width=DISPLAY_WIDTH,
                              height=DISPLAY_HEIGHT, data=data)

    timeAtStart = time.time()
    timeNow = time.time()

    while True:
        if (timeNow - timeAtStart >= config["refreshTime"]):
            if config["apiMethod"] == 'rtt':
                data = loadDataRTT(config["rttApi"], config["journey"])
            # else:
            #     data = loadData(config["transportApi"], config["journey"])
                
            if len(data[0]) == 0:
                virtual = drawBlankSignage(
                    device, width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT, departureStation=data[2])
            else:
                virtual = drawSignage(device, width=DISPLAY_WIDTH,
                                      height=DISPLAY_HEIGHT, data=data)

            timeAtStart = time.time()

        timeNow = time.time()
        virtual.refresh()

except KeyboardInterrupt:
    pass
except ValueError as err:
    print(f"Error: {err}")

    #this is debug
def loadDestinationsForDepartureRTT(journeyConfig, username, password, timetableUrl):
    print(f"Requesting timetable data from: {timetableUrl}")
    response = requests.get(url=timetableUrl, auth=(username, password))

    # Check if the response is in JSON format
    try:
        calling_data = response.json()
    except json.JSONDecodeError:
        print(f"Error decoding JSON response. Response content: {response.text}")
        return []

    # Print the full JSON response for debugging
    print(f"Received response: {json.dumps(calling_data, indent=2)}")  # Pretty-print the JSON response

    # Temporarily bypass the need for 'locations'
    return []

# Example usage
journeyConfig = {
    "departureStation": "FRM",
    # Add other necessary journey config here
}
username = "your_username"
password = "your_password"
timetableUrl = "https://api.rtt.io/api/v1/json/service/L58427/2024/07/06"

# Call the function
loadDestinationsForDepartureRTT(journeyConfig, username, password, timetableUrl)
