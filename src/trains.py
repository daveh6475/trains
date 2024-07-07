import requests
import re
import json  # Ensure this line is included
import xmltodict
from datetime import date
from dataclasses import dataclass
from typing import Any, List, Tuple
import xml.etree.ElementTree as ET


def removeBrackets(originalName):
    return re.split(r" \(", originalName)[0]

def isTime(value):
    matches = re.findall(r"\d{2}:\d{2}", value)
    return len(matches) > 0

def joinwithCommas(listIN):
    return ", ".join(listIN)[::-1].replace(",", "dna ", 1)[::-1]

def removeEmptyStrings(items):
    return filter(None, items)

def joinWith(items, joiner: str):
    filtered_list = removeEmptyStrings(items)
    return joiner.join(filtered_list)

def joinWithSpaces(*args):
    return joinWith(args, " ")

def prepareServiceMessage(operator):
    return joinWithSpaces("A" if operator not in ['Elizabeth Line', 'Avanti West Coast'] else "An", operator, "Service")

def prepareLocationName(location, show_departure_time):
    location_name = removeBrackets(location['lt7:locationName'])

    if not show_departure_time:
        return location_name
    else:
        scheduled_time = location["lt7:st"]
        try:
            expected_time = location["lt7:et"]
        except KeyError:
            # as per api docs, it's 'at' if there isn't an 'et':
            expected_time = location["lt7:at"]
        departure_time = expected_time if isTime(expected_time) else scheduled_time
        formatted_departure = joinWith(["(", departure_time, ")"], "")
        return joinWithSpaces(location_name, formatted_departure)

def prepareCarriagesMessage(carriages):
    if carriages == 0:
        return ""
    else:
        return joinWithSpaces("formed of", carriages, "coaches.")

def ArrivalOrder(ServicesIN):
    ServicesOUT = []
    for servicenum, eachService in enumerate(ServicesIN):
        STDHour = int(eachService['lt4:std'][0:2])
        STDMinute = int(eachService['lt4:std'][3:5])
        if (STDHour < 2):
            STDHour += 24  # this prevents a 12am departure displaying before a 11pm departure
        STDinMinutes = STDHour * 60 + STDMinute  # this service is at this many minutes past midnight
        ServicesOUT.append(eachService)
        ServicesOUT[servicenum]['sortOrder'] = STDinMinutes
    ServicesOUT = sorted(ServicesOUT, key=lambda k: k['sortOrder'])
    return ServicesOUT

def ProcessDepartures(journeyConfig, APIOut):
    show_individual_departure_time = journeyConfig["individualStationDepartureTime"]
    APIElements = xmltodict.parse(APIOut)
    Services = []

    # get departure station name
    departureStationName = APIElements['soap:Envelope']['soap:Body']['GetDepBoardWithDetailsResponse']['GetStationBoardResult']['lt4:locationName']

    # if there are only train services from this station
    if 'lt7:trainServices' in APIElements['soap:Envelope']['soap:Body']['GetDepBoardWithDetailsResponse']['GetStationBoardResult']:
        Services = APIElements['soap:Envelope']['soap:Body']['GetDepBoardWithDetailsResponse']['GetStationBoardResult']['lt7:trainServices']['lt7:service']
        if isinstance(Services, dict):  # if there's only one service, it comes out as a dict
            Services = [Services]       # but it needs to be a list with a single element

        # if there are train and bus services from this station
        if 'lt7:busServices' in APIElements['soap:Envelope']['soap:Body']['GetDepBoardWithDetailsResponse']['GetStationBoardResult']:
            BusServices = APIElements['soap:Envelope']['soap:Body']['GetDepBoardWithDetailsResponse']['GetStationBoardResult']['lt7:busServices']['lt7:service']
            if isinstance(BusServices, dict):
                BusServices = [BusServices]
            Services = ArrivalOrder(Services + BusServices)  # sort the bus and train services into one list in order of scheduled arrival time

    # if there are only bus services from this station
    elif 'lt7:busServices' in APIElements['soap:Envelope']['soap:Body']['GetDepBoardWithDetailsResponse']['GetStationBoardResult']:
        Services = APIElements['soap:Envelope']['soap:Body']['GetDepBoardWithDetailsResponse']['GetStationBoardResult']['lt7:busServices']['lt7:service']
        if isinstance(Services, dict):
            Services = [Services]

    # if there are no trains or buses
    else:
        Services = None
        return None, departureStationName

    # we create a new list of dicts to hold the services
    Departures = [{}] * len(Services)

    for servicenum, eachService in enumerate(Services):
        thisDeparture = {}  # create empty dict to populate

        # next we move elements of dict eachService to dict thisDeparture one by one

        # get platform, if available
        if 'lt4:platform' in eachService:
            thisDeparture["platform"] = (eachService['lt4:platform'])

        # get scheduled departure time
        thisDeparture["aimed_departure_time"] = eachService["lt4:std"]

        # get estimated departure time
        thisDeparture["expected_departure_time"] = eachService["lt4:etd"]

        # get carriages, if available
        if 'lt4:length' in eachService:
            thisDeparture["carriages"] = eachService["lt4:length"]
        else:
            thisDeparture["carriages"] = 0

        # get operator, if available
        if 'lt4:operator' in eachService:
            thisDeparture["operator"] = eachService["lt4:operator"]

        # get name of destination
        if not isinstance(eachService['lt5:destination']['lt4:location'], list):    # the service only has one destination
            thisDeparture["destination_name"] = removeBrackets(eachService['lt5:destination']['lt4:location']['lt4:locationName'])
        else:  # the service splits and has multiple destinations
            DestinationList = [i['lt4:locationName'] for i in eachService['lt5:destination']['lt4:location']]
            thisDeparture["destination_name"] = " & ".join([removeBrackets(i) for i in DestinationList])

        # get via and add to destination name
        # if 'lt4:via' in eachService['lt5:destination']['lt4:location']:
        #    thisDeparture["destination_name"] += " " + eachService['lt5:destination']['lt4:location']['lt4:via']

            # get calling points
        if 'lt7:subsequentCallingPoints' in eachService:  # there are some calling points
            # check if it is a list of lists    (the train splits, so there are multiple lists of calling points)
            # or a dict                         (the train does not split. There is one list of calling points)
            if not isinstance(eachService['lt7:subsequentCallingPoints']['lt7:callingPointList'], dict):
                # there are multiple lists of calling points
                CallingPointList = eachService['lt7:subsequentCallingPoints']['lt7:callingPointList']
                CallLists = []
                CallListJoined = []
                for sectionNum, eachSection in enumerate(CallingPointList):
                    if isinstance(eachSection['lt7:callingPoint'], dict):
                        # there is only one calling point in this list
                        CallLists.append([prepareLocationName(eachSection['lt7:callingPoint'], show_individual_departure_time)])
                        CallListJoined.append(CallLists[sectionNum])
                    else:  # there are several calling points in this list
                        CallLists.append([prepareLocationName(i, show_individual_departure_time) for i in eachSection['lt7:callingPoint']])

                        CallListJoined.append(joinwithCommas(CallLists[sectionNum]))
                        # CallListJoined.append(", ".join(CallLists[sectionNum]))
                thisDeparture["calling_at_list"] = joinWithSpaces(
                    " with a portion going to ".join(CallListJoined),
                    "  --  ",
                    prepareServiceMessage(thisDeparture["operator"]),
                    prepareCarriagesMessage(thisDeparture["carriages"])
                )

            else:  # there is one list of calling points
                if isinstance(eachService['lt7:subsequentCallingPoints']['lt7:callingPointList']['lt7:callingPoint'], dict):
                    # there is only one calling point in the list
                    thisDeparture["calling_at_list"] = joinWithSpaces(
                        prepareLocationName(eachService['lt7:subsequentCallingPoints']['lt7:callingPointList']['lt7:callingPoint'], show_individual_departure_time),
                        "only.",
                        "  --  ",
                        prepareServiceMessage(thisDeparture["operator"]),
                        prepareCarriagesMessage(thisDeparture["carriages"])
                    )
                else:  # there are several calling points in the list
                    CallList = [prepareLocationName(i, show_individual_departure_time) for i in eachService['lt7:subsequentCallingPoints']['lt7:callingPointList']['lt7:callingPoint']]
                    thisDeparture["calling_at_list"] = joinWithSpaces(
                        joinwithCommas(CallList) + ".",
                        " --  ",
                        prepareServiceMessage(thisDeparture["operator"]),
                        prepareCarriagesMessage(thisDeparture["carriages"])
                    )
        else:  # there are no calling points, so just display the destination
            thisDeparture["calling_at_list"] = joinWithSpaces(
                thisDeparture["destination_name"],
                "only.",
                prepareServiceMessage(thisDeparture["operator"]),
                prepareCarriagesMessage(thisDeparture["carriages"])
            )
        # print("the " + thisDeparture["aimed_departure_time"] + " calls at " + thisDeparture["calling_at_list"])

        Departures[servicenum] = thisDeparture

    return Departures, departureStationName

import requests

def loadDeparturesForStation(journeyConfig, apiKey, rows):
    if journeyConfig["departureStation"] == "":
        raise ValueError("Please configure the departureStation environment variable")

    if apiKey is None:
        raise ValueError("Please configure the apiKey environment variable")

    destinationStation = journeyConfig["destinationStation"] or ""
    timeOffset = journeyConfig["timeOffset"] or "0"

    APIRequest = f"""
    <x:Envelope xmlns:x="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ldb="http://thalesgroup.com/RTTI/2017-10-01/ldb/" xmlns:typ4="http://thalesgroup.com/RTTI/2013-11-28/Token/types">
    <x:Header>
        <typ4:AccessToken><typ4:TokenValue>{apiKey}</typ4:TokenValue></typ4:AccessToken>
    </x:Header>
    <x:Body>
        <ldb:GetDepBoardWithDetailsRequest>
            <ldb:numRows>{rows}</ldb:numRows>
            <ldb:crs>{journeyConfig["departureStation"]}</ldb:crs>
            <ldb:timeOffset>{timeOffset}</ldb:timeOffset>
            <ldb:filterCrs>{destinationStation}</ldb:filterCrs>
            <ldb:filterType>to</ldb:filterType>
            <ldb:timeWindow>120</ldb:timeWindow>
        </ldb:GetDepBoardWithDetailsRequest>
    </x:Body>
    </x:Envelope>"""

    headers = {'Content-Type': 'text/xml'}
    apiURL = "https://lite.realtime.nationalrail.co.uk/OpenLDBWS/ldb11.asmx"

    try:
        response = requests.post(apiURL, data=APIRequest, headers=headers)
        response.raise_for_status()
        APIOut = response.text
        print(f"API Response:\n{APIOut}")  # Debug statement to print the XML response
    except requests.RequestException as e:
        print(f"API request failed: {e}")
        return None, None

    Departures, departureStationName = ProcessDepartures(journeyConfig, APIOut)

    return Departures, departureStationName

def ProcessDepartures(journeyConfig, APIOut):
    root = ET.fromstring(APIOut)
    ns = {
        'x': 'http://schemas.xmlsoap.org/soap/envelope/',
        'ldb': 'http://thalesgroup.com/RTTI/2017-10-01/ldb/'
    }

    locationNameElement = root.find('.//ldb:locationName', ns)
    if locationNameElement is None:
        print("Error: locationName element not found in the XML response.")
        return None, None
    stationName = locationNameElement.text

    services = root.findall('.//ldb:service', ns)
    departures = []

    for service in services:
        aimed_departure_time = service.find('ldb:std', ns).text
        expected_departure_time = service.find('ldb:etd', ns).text
        destination_name = service.find('.//ldb:destination/ldb:location/ldb:locationName', ns).text
        platform = service.find('ldb:platform', ns).text if service.find('ldb:platform', ns) is not None else ''

        calling_at_list = [loc.find('ldb:locationName', ns).text for loc in service.findall('.//ldb:subsequentCallingPoints/ldb:callingPointList/ldb:callingPoint/ldb:locationName', ns)]

        departure = {
            "aimed_departure_time": aimed_departure_time,
            "expected_departure_time": expected_departure_time,
            "destination_name": destination_name,
            "platform": platform,
            "calling_at_list": calling_at_list
        }
        departures.append(departure)

    return departures, stationName
