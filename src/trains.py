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
    try:
        departureStationName = APIElements['soap:Envelope']['soap:Body']['GetDepBoardWithDetailsResponse']['GetStationBoardResult']['lt4:locationName']
    except KeyError:
        print("Error: locationName element not found in the XML response.")
        return None, None

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

def loadDeparturesForStation(journeyConfig, apiKey, rows):
    try:
        stationCode = journeyConfig["station"]
    except KeyError as e:
        print(f"Key Error: {e} in journeyConfig: {journeyConfig}")
        return None, "Unknown Station"

    url = journeyConfig["apiUrl"]  # Ensure this key exists in journeyConfig

    headers = {
        "Content-Type": "text/xml",
        "SOAPAction": "http://thalesgroup.com/RTTI/2012-01-13/ldb/GetDepBoardWithDetails",
    }

    body = f"""<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
               xmlns:ldb="http://thalesgroup.com/RTTI/2012-01-13/ldb/types"
               xmlns:typ="http://thalesgroup.com/RTTI/2010-11-01/ldb/types">
                 <soap:Header>
                   <typ:AccessToken>
                     <typ:TokenValue>{apiKey}</typ:TokenValue>
                   </typ:AccessToken>
                 </soap:Header>
                 <soap:Body>
                   <ldb:GetDepBoardWithDetailsRequest>
                     <ldb:numRows>{rows}</ldb:numRows>
                     <ldb:crs>{stationCode}</ldb:crs>
                   </ldb:GetDepBoardWithDetailsRequest>
                 </soap:Body>
               </soap:Envelope>"""

    try:
        response = requests.post(url, data=body, headers=headers)
        response.raise_for_status()

        print(f"API Response:\n{response.text}")  # Debugging statement

        root = ET.fromstring(response.content)
        namespace = {'soap': 'http://schemas.xmlsoap.org/soap/envelope/', 
                     'ldb': 'http://thalesgroup.com/RTTI/2012-01-13/ldb/types'}

        try:
            stationName = root.find('.//ldb:locationName', namespace).text
            services = root.findall('.//ldb:service', namespace)
            departures = []

            for service in services:
                departure = {
                    "aimed_departure_time": service.find('.//ldb:std', namespace).text,
                    "expected_departure_time": service.find('.//ldb:etd', namespace).text,
                    "platform": service.find('.//ldb:platform', namespace).text if service.find('.//ldb:platform', namespace) is not None else "",
                    "destination_name": service.find('.//ldb:destination//ldb:location//ldb:locationName', namespace).text,
                    "calling_at_list": [cp.find('.//ldb:locationName', namespace).text for cp in service.findall('.//ldb:subsequentCallingPoints//ldb:callingPoint', namespace)]
                }
                departures.append(departure)

            print(f"Station Name: {stationName}")
            print(f"Departures: {departures}")
            return departures, stationName

        except AttributeError as err:
            print(f"Attribute Error: {err}")
            print("Could not find one or more required elements in the XML response.")
            return None, "Unknown Station"
        except Exception as err:
            print(f"Unexpected Error: {err}")
            return None, "Unknown Station"
    except requests.RequestException as e:
        print(f"Request Error: {e}")
        return None, "Unknown Station"

# Example usage
if __name__ == "__main__":
    apiKey = 'bda3de70-1f9e-4d80-a293-33c1900eb18d'
    journeyConfig = {
        "station": "FRM",
        "apiUrl": "https://lite.realtime.nationalrail.co.uk/OpenLDBWS/ldb11.asmx"
    }
    rows = 10

    departures, stationName = loadDeparturesForStation(journeyConfig, apiKey, rows)
    if departures is not None:
        print(f"Departures from {stationName}:")
        for departure in departures:
            print(departure)
    else:
        print(f"Failed to load departures for station: {stationName}")
        
def ProcessDepartures(journeyConfig, APIOut):
    show_individual_departure_time = journeyConfig.get("individualStationDepartureTime", False)
    APIElements = xmltodict.parse(APIOut)

    Services = []

    try:
        # Namespaces
        namespaces = {
            'soap': "http://schemas.xmlsoap.org/soap/envelope/",
            'ldb': "http://thalesgroup.com/RTTI/2017-10-01/ldb/",
            'lt4': "http://thalesgroup.com/RTTI/2015-11-27/ldb/types",
            'lt7': "http://thalesgroup.com/RTTI/2017-10-01/ldb/types",
            'lt5': "http://thalesgroup.com/RTTI/2016-02-16/ldb/types"
        }

        departureStationName = APIElements['soap:Envelope']['soap:Body']['ldb:GetDepBoardWithDetailsResponse']['ldb:GetStationBoardResult']['lt4:locationName']

    except KeyError:
        print("Error: locationName element not found in the XML response.")
        return None, None

    if 'lt7:trainServices' in APIElements['soap:Envelope']['soap:Body']['ldb:GetDepBoardWithDetailsResponse']['ldb:GetStationBoardResult']:
        Services = APIElements['soap:Envelope']['soap:Body']['ldb:GetDepBoardWithDetailsResponse']['ldb:GetStationBoardResult']['lt7:trainServices']['lt7:service']
        if isinstance(Services, dict):
            Services = [Services]

        if 'lt7:busServices' in APIElements['soap:Envelope']['soap:Body']['ldb:GetDepBoardWithDetailsResponse']['ldb:GetStationBoardResult']:
            BusServices = APIElements['soap:Envelope']['soap:Body']['ldb:GetDepBoardWithDetailsResponse']['ldb:GetStationBoardResult']['lt7:busServices']['lt7:service']
            if isinstance(BusServices, dict):
                BusServices = [BusServices]
            Services = ArrivalOrder(Services + BusServices)

    elif 'lt7:busServices' in APIElements['soap:Envelope']['soap:Body']['ldb:GetDepBoardWithDetailsResponse']['ldb:GetStationBoardResult']:
        Services = APIElements['soap:Envelope']['soap:Body']['ldb:GetDepBoardWithDetailsResponse']['ldb:GetStationBoardResult']['lt7:busServices']['lt7:service']
        if isinstance(Services, dict):
            Services = [Services]

    else:
        Services = None
        return None, departureStationName

    Departures = [{}] * len(Services)

    for servicenum, eachService in enumerate(Services):
        thisDeparture = {}

        if 'lt4:platform' in eachService:
            thisDeparture["platform"] = eachService['lt4:platform']

        thisDeparture["aimed_departure_time"] = eachService["lt4:std"]
        thisDeparture["expected_departure_time"] = eachService["lt4:etd"]

        if 'lt4:length' in eachService:
            thisDeparture["carriages"] = eachService["lt4:length"]
        else:
            thisDeparture["carriages"] = 0

        if 'lt4:operator' in eachService:
            thisDeparture["operator"] = eachService["lt4:operator"]

        if not isinstance(eachService['lt5:destination']['lt4:location'], list):
            thisDeparture["destination_name"] = removeBrackets(eachService['lt5:destination']['lt4:location']['lt4:locationName'])
        else:
            DestinationList = [i['lt4:locationName'] for i in eachService['lt5:destination']['lt4:location']]
            thisDeparture["destination_name"] = " & ".join([removeBrackets(i) for i in DestinationList])

        if 'lt7:subsequentCallingPoints' in eachService:
            if not isinstance(eachService['lt7:subsequentCallingPoints']['lt7:callingPointList'], dict):
                CallingPointList = eachService['lt7:subsequentCallingPoints']['lt7:callingPointList']
                CallLists = []
                CallListJoined = []
                for sectionNum, eachSection in enumerate(CallingPointList):
                    if isinstance(eachSection['lt7:callingPoint'], dict):
                        CallLists.append([prepareLocationName(eachSection['lt7:callingPoint'], show_individual_departure_time)])
                        CallListJoined.append(CallLists[sectionNum])
                    else:
                        CallLists.append([prepareLocationName(i, show_individual_departure_time) for i in eachSection['lt7:callingPoint']])
                        CallListJoined.append(joinwithCommas(CallLists[sectionNum]))
                thisDeparture["calling_at_list"] = joinWithSpaces(
                    " with a portion going to ".join(CallListJoined),
                    "  --  ",
                    prepareServiceMessage(thisDeparture["operator"]),
                    prepareCarriagesMessage(thisDeparture["carriages"])
                )
            else:
                if isinstance(eachService['lt7:subsequentCallingPoints']['lt7:callingPointList']['lt7:callingPoint'], dict):
                    thisDeparture["calling_at_list"] = joinWithSpaces(
                        prepareLocationName(eachService['lt7:subsequentCallingPoints']['lt7:callingPointList']['lt7:callingPoint'], show_individual_departure_time),
                        "only.",
                        "  --  ",
                        prepareServiceMessage(thisDeparture["operator"]),
                        prepareCarriagesMessage(thisDeparture["carriages"])
                    )
                else:
                    CallList = [prepareLocationName(i, show_individual_departure_time) for i in eachService['lt7:subsequentCallingPoints']['lt7:callingPointList']['lt7:callingPoint']]
                    thisDeparture["calling_at_list"] = joinWithSpaces(
                        joinwithCommas(CallList) + ".",
                        " --  ",
                        prepareServiceMessage(thisDeparture["operator"]),
                        prepareCarriagesMessage(thisDeparture["carriages"])
                    )
        else:
            thisDeparture["calling_at_list"] = joinWithSpaces(
                thisDeparture["destination_name"],
                "only.",
                prepareServiceMessage(thisDeparture["operator"]),
                prepareCarriagesMessage(thisDeparture["carriages"])
            )

        Departures[servicenum] = thisDeparture

    return Departures, departureStationName
