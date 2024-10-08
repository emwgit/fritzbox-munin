#!/usr/bin/env python3
"""
  fritzbox_smart_home_temperature - A munin plugin for Linux to monitor AVM Fritzbox SmartHome temperatures
  Copyright (C) 2018 Bernd Oerding, 2021 Ernst Martin Witte
  Authors: Bernd Oerding, Ernst Martin Witte
  Like Munin, this plugin is licensed under the GNU GPL v2 license
  http://www.opensource.org/licenses/GPL-2.0
  Add the following section to your munin-node's plugin configuration:

  [fritzbox_*]
  env.fritzbox_ip       [ip address of the fritzbox]
  env.fritzbox_username [optionial, if you configured the FritzBox to use user and password]
  env.fritzbox_password [fritzbox password]
  
  This plugin supports the following munin configuration parameters:
  #%# family=auto contrib
  #%# capabilities=autoconf
"""

import json
import os
import re
import sys
import pprint
from FritzboxInterface import FritzboxInterface

PAGE   = 'data.lua'
PARAMS = {"xhr": 1, 'lang': 'en', 'page': 'sh', 'xhrId': 'all', 'no_sidrenew': None}


def getSimplifiedDevices(debug=False):
    

    if debug :
        pp = pprint.PrettyPrinter(indent=4)
        
    if debug:
        print("requesting data through postPageWithLogin")
        
    data = FritzboxInterface().postPageWithLogin(PAGE, data = PARAMS)
    
    if debug:
        pp.pprint(data)
        
    simplifiedDevices = dict()
    
    devices = data["data"]["devices"]
    for device in devices:
        devDisplayName = device["displayName"]
        category       = device["category"]
        deviceType     = device["type"]
        units          = device["units"]
        connected      = device["masterConnectionState"]
        devID          = device["id"]

        simpleDev      = { "id"          : devID,
                           "displayName" : devDisplayName,
                           "present"     : connected == "CONNECTED",
                           "model"       : device["model"],
                           "identifier"  : device["actorIdentificationNumber"],
        }

        if debug:
            print(f"device {devDisplayName}: cat:{category}, type:{deviceType}, con:{connected}")
        
        for unit in units:
            unitDisplayName = unit["displayName"]
            skills          = unit["skills"]
            unitType        = unit["type"]
            unitID          = unit["id"]

            if debug:
                print(f"    unit {unitDisplayName}: type:{unitType}")
            
            for skill in skills:
                skillType = skill["type"]
                
                if debug:
                    print(f"        skill, type:{skillType}")
                    
                if (skillType == "SmartHomeThermostat"): 
                    
                    if "mode" in skill:
                        simpleDev["mode"                   ] = skill["mode"]

                    # new state reporting in Fritz!OS 7.51/7.56
                    if "state" in skill:
                        state = skill["state"]
                        if "current" in state:
                            simpleDev["summerActive"] = 1 if state["current"] == "SUMMER"      else 0
                            simpleDev["holidyActive"] = 1 if state["current"] == "HOLIDAY"     else 0  # FIXME: guess, to be tested
                            simpleDev["windowOpen"  ] = 1 if state["current"] == "WINDOW_OPEN" else 0  # FIXME: guess, to be tested
                        # end if
                    # end if
                                
                        
                    # old state reporting in Fritz!OS 7.29/7.31
                    if "summerActive" in skill:
                        simpleDev["summerActive"           ] = skill["summerActive"]
                        
                    # old state reporting in Fritz!OS 7.29/7.31
                    if "holidayActive" in skill:
                        simpleDev["holidayActive"          ] = skill["holidayActive"]
                        
                    # old state reporting in Fritz!OS 7.29/7.31
                    if "temperatureDropDetection" in skill and "isWindowOpen" in skill["temperatureDropDetection"]:
                        simpleDev["windowOpen"             ] = skill["temperatureDropDetection"]["isWindowOpen"]
                        
                    if "targetTemp" in skill:
                        simpleDev["targetTemperatureInDegC"] = skill["targetTemp"]
                    else:
                        simpleDev["targetTemperatureInDegC"] = None
                        
                    if "usedTempSensor" in skill:
                        refSkills = skill["usedTempSensor"]["skills"]
                        for refSkill in refSkills:
                            if "currentInCelsius" in refSkill:
                                simpleDev["refTemperatureInDegC"] = refSkill["currentInCelsius"]
                        
                elif (skillType == "SmartHomeTemperatureSensor"):

                    # let's    not    blindly    assume    that    the
                    # currentInCelsius is  there.  Seems that  after a
                    # fritzbox  restart,   thermostats  are   not  yet
                    # connected properly to the fritz box and that the
                    # report has the  devices, but without temperature
                    # entry until DECT connection is established again.
                    simpleDev["currentTemperatureInDegC"] = skill["currentInCelsius"]     if ("currentInCelsius"     in skill) else None
                    
                elif (skillType == "SmartHomeHumiditySensor"):

                    # Why this check: See skill["currentInCelsius"]
                    simpleDev["currentHumidityInPct"]     = skill["currentInPercent"]     if ("currentInPercent"     in skill) else None
                    
                elif (skillType == "SmartHomeBattery"):
                    
                    # Why this check: See skill["currentInCelsius"]
                    simpleDev["batteryChargeLevelInPct"]  = skill["chargeLevelInPercent"] if ("chargeLevelInPercent" in skill) else None

                    # FIXME: currently no batteryLow indicator available
                    # simpleDev["batteryLow"] = FIXME
                    
                elif (skillType == "SmartHomeMultimeter"):

                    if "electricCurrentInAmpere" in skill:
                        simpleDev["currentInAmp"] = skill["electricCurrentInAmpere"]

                    if "powerConsumptionInWatt" in skill:
                        simpleDev["powerInWatt"] = skill["powerConsumptionInWatt"]

                    if "powerPerHour" in skill:
                        simpleDev["energyInKWH"] = float(skill["powerPerHour"]) / 1000

                    if "voltageInVolt" in skill:
                        simpleDev["voltageInVolt"] = skill["voltageInVolt"]

                elif (skillType == "SmartHomeSocket"):
                    pass
                                  
                elif (skillType == "SmartHomeSwitch"):

                    if "state" in skill:
                        simpleDev["powerSwitchOn"] = skill["state"] == "ON"
                                  
                # end select skillType                
            # end for each skill
        # end for each unit


        simplifiedDevices[devID] = simpleDev

        if debug:
            pp.pprint(simpleDev)
    # end for each device

    if debug:
        pp.pprint(simplifiedDevices)

    return simplifiedDevices

# end getSimplifiedDevices




def print_smart_home_measurements(simpleDevices, debug=False):
    """get the current measurements (temperature, humidity, power, states, ...)"""

    
    print("multigraph temperatures")
        
    for dev in simpleDevices:
        
        if dev["present"] and "currentTemperatureInDegC" in dev:
            print ("t{}.value {}"    .format(dev["id"], dev["currentTemperatureInDegC"]))

            
    print("")
    print("multigraph humidity")
    for dev in simpleDevices:
        
        if dev["present"] and "currentHumidityInPct" in dev:
            print ("humidity{}.value {}".format(dev["id"], dev["currentHumidityInPct"])) 
            



    print("\n")
    print("multigraph temperatures_target")
        
    for dev in simpleDevices:
        
        if dev["present"] and "targetTemperatureInDegC" in dev and dev["targetTemperatureInDegC"] is not None:
            print ("tsoll{}.value {}"    .format(dev["id"], dev["targetTemperatureInDegC"]))
            
    for dev in simpleDevices:
        
        if dev["present"]:

            print("")
            print("multigraph temperatures.t{}".format(dev["id"]))
            
            if "refTemperatureInDegC" in dev:
                print ("tref{}.value {}"    .format(dev["id"], dev["refTemperatureInDegC"]))
                
            if "currentTemperatureInDegC" in dev:
                print ("t{}.value {}"    .format(dev["id"], dev["currentTemperatureInDegC"]))
                
            if "targetTemperatureInDegC" in dev and dev["targetTemperatureInDegC"] is not None:
                print ("tsoll{}.value {}"    .format(dev["id"], dev["targetTemperatureInDegC"]))



    print("\n")
    print("multigraph thermostat_modes")
    
    for dev in simpleDevices:

        if dev["present"] and "windowOpen" in dev:
            print ("windowopenmode{}.value {}"    .format(dev["id"], int(dev["windowOpen"])))

            
    for dev in simpleDevices:

        if "windowOpen" in dev or "summerActive" in dev or "holidayActive" in dev:
            
            print("\n")
            print("multigraph thermostat_modes.id{}".format(dev["id"]))

            if "windowOpen" in dev:
                print ("windowopenmode{}.value {}"                                  .format(dev["id"], int(dev["windowOpen"]))) 

            if "summerActive" in dev:
                print ("summermode{}.value {}"                                      .format(dev["id"], int(dev["summerActive"])))

            if "holidayActive" in dev:
                print ("holidaymode{}.value {}"                                     .format(dev["id"], int(dev["holidayActive"]))) 

                
    print("")
    print("multigraph battery")
    for dev in simpleDevices:
        
        if dev["present"] and "batteryChargeLevelInPct" in dev:
            print ("battery{}.value {}".format(dev["id"], dev["batteryChargeLevelInPct"])) 
            

                
                
    print("")
    print("multigraph batterylow")
    for dev in simpleDevices:
        
        if dev["present"] and "batteryLow" in dev:
            print ("batterylow{}.value {}".format(dev["id"], dev["batteryLow"]))
        

                
    print("")
    print("multigraph voltage")
    for dev in simpleDevices:
        
        if dev["present"] and "voltageInVolt" in dev:
            print ("voltage{}.value {}".format(dev["id"], dev["voltageInVolt"]))
        

                
    print("")
    print("multigraph smarthome_power")
    for dev in simpleDevices:
        
        if dev["present"] and "powerInWatt" in dev:
            print ("smarthome_power{}.value {}".format(dev["id"], dev["powerInWatt"]))

            
    print("")
    print("multigraph smarthome_powerAvg")
    for dev in simpleDevices:
        
        if dev["present"] and "energyInKWH" in dev:
            # it is ok to use integer Joules here: 1 Joule in 5 min
            # => 0.003 W precision => We don't care, the device doesn't have this precision
            energyInJoule = int(dev["energyInKWH"] * 3600000)
            devID         = dev["id"]
            print (f"smarthome_powerAvg{devID}.value {energyInJoule:15}")
        # end 

    print("")
    print("multigraph energy")
    for dev in simpleDevices:
        
        if dev["present"] and "energyInKWH" in dev:
            print ("energy{}.value {}".format(dev["id"], dev["energyInKWH"]))

    print("")
    print("multigraph smarthome_powerswitch")
    for dev in simpleDevices:
        
        if dev["present"] and "powerSwitchOn" in dev:
            print ("smarthome_powerswitch{}.value {}".format(dev["id"], int(dev["powerSwitchOn"])))
            

def getDevices(debug=False):
    
    simpleDevicesDict = getSimplifiedDevices(debug)
    simpleDevices     = sorted(simpleDevicesDict.values(), key = lambda x: x["displayName"])

    return simpleDevices
# end getDevices
                

def print_config(simpleDevices, debug=False):

    
    
    print("multigraph temperatures")
    print("graph_title AVM Fritz!Box SmartHome Temperatures (locally measured)")
    print("graph_vlabel degrees Celsius")
    print("graph_category smart home")
    print("graph_scale no")
    print("")

    for dev in simpleDevices:
    
        if "currentTemperatureInDegC" in dev:
            print ("t{}.label {}"                                        .format(dev["id"], dev["displayName"])) 
            print ("t{}.type GAUGE"                                      .format(dev["id"])) 
            print ("t{}.graph LINE"                                      .format(dev["id"])) 
            print ("t{}.info Locally measured temperature [{} - {}]"     .format(dev["id"], dev["model"], dev["identifier"]))

            
    print("\n")
    print("multigraph humidity")
    print("graph_title AVM Fritz!Box SmartHome Humidity")
    print("graph_vlabel percent")
    print("graph_category smart home")
    print("graph_scale no")
    print("\n")


    for dev in simpleDevices:
        if dev["present"] and "currentHumidityInPct" in dev:
            print ("humidity{}.label {}"                                  .format(dev["id"], dev["displayName"])) 
            print ("humidity{}.type GAUGE"                                .format(dev["id"])) 
            print ("humidity{}.graph LINE"                                .format(dev["id"])) 
            print ("humidity{}.max 100"                                   .format(dev["id"])) 
            print ("humidity{}.min   0"                                   .format(dev["id"])) 
            print ("humidity{}.warning 30:70"                             .format(dev["id"])) 
            print ("humidity{}.critical 20:75"                            .format(dev["id"])) 
            print ("humidity{}.info Humidity [{} - {}]"                   .format(dev["id"], dev["model"], dev["identifier"]))




    print("\n")
    print("multigraph temperatures_target")
    print("graph_title AVM Fritz!Box SmartHome Target Temperatures")
    print("graph_vlabel degrees Celsius")
    print("graph_category smart home")
    print("graph_scale no")
    print("")

    for dev in simpleDevices:
    
        if "targetTemperatureInDegC" in dev:
            print ("tsoll{}.label {}"                                    .format(dev["id"], dev["displayName"])) 
            print ("tsoll{}.type GAUGE"                                  .format(dev["id"])) 
            print ("tsoll{}.graph LINE"                                  .format(dev["id"])) 
            print ("tsoll{}.info Target temperature [{} - {}]"           .format(dev["id"], dev["model"], dev["identifier"]))
            

    for dev in simpleDevices:
        print("\n")
        print("multigraph temperatures.t{}".format(dev["id"]))
        print("graph_title Temperatures for {}".format(dev["displayName"]))
        print("graph_vlabel degrees Celsius")
        print("graph_category smart home")
        print("graph_scale no")
        print("\n")

        if "currentTemperatureInDegC" in dev:
            print ("t{}.label measured locally"                          .format(dev["id"])) 
            print ("t{}.type GAUGE"                                      .format(dev["id"])) 
            print ("t{}.graph LINE"                                      .format(dev["id"])) 
            print ("t{}.warning 15:30"                                   .format(dev["id"])) 
            print ("t{}.critical 10:35"                                  .format(dev["id"])) 
            print ("t{}.info Locally measured temperature [{} - {}]"     .format(dev["id"], dev["model"], dev["identifier"]))

        if "refTemperatureInDegC" in dev:
            print ("tref{}.label measured ref."                          .format(dev["id"]))
            print ("tref{}.type GAUGE"                                   .format(dev["id"])) 
            print ("tref{}.graph LINE"                                   .format(dev["id"])) 
            print ("tref{}.info Measured reference temperature [{} - {}]".format(dev["id"], dev["model"], dev["identifier"]))

        if "targetTemperatureInDegC" in dev:
            print ("tsoll{}.label target"                                .format(dev["id"]))
            print ("tsoll{}.type GAUGE"                                  .format(dev["id"])) 
            print ("tsoll{}.graph LINE"                                  .format(dev["id"])) 
            print ("tsoll{}.info Target temperature [{} - {}]"           .format(dev["id"], dev["model"], dev["identifier"]))
            

    print("\n")
    print("multigraph thermostat_modes")
    print("graph_title AVM Fritz!Box SmartHome Thermostat Modes")
    print("graph_vlabel on/off")
    print("graph_category smart home")
    print("graph_scale no")
    print("\n")
    
    for dev in simpleDevices:

        if dev["present"] and "windowOpen" in dev:
            print ("windowopenmode{}.label {}"                                  .format(dev["id"], dev["displayName"])) 
            print ("windowopenmode{}.type GAUGE"                                .format(dev["id"]))
            print ("windowopenmode{}.graph LINE"                                .format(dev["id"]))
            print ("windowopenmode{}.max   1"                                   .format(dev["id"]))
            print ("windowopenmode{}.min   0"                                   .format(dev["id"]))
            print ("windowopenmode{}.info Window Open Mode [{} - {}]"           .format(dev["id"], dev["model"], dev["identifier"]))


    for dev in simpleDevices:

        if "windowOpen" in dev or "summerActive" in dev or "holidayActive" in dev:
            
            print("\n")
            print("multigraph thermostat_modes.id{}".format(dev["id"]))
            print("graph_title AVM Fritz!Box SmartHome Modes for {}".format(dev["displayName"]))
            print("graph_vlabel on/off")
            print("graph_category smart home")
            print("graph_scale no")
            print("\n")

            if "windowOpen" in dev:
                print ("windowopenmode{}.label Window Open"                         .format(dev["id"])) 
                print ("windowopenmode{}.type  GAUGE"                               .format(dev["id"])) 
                print ("windowopenmode{}.graph LINE"                                .format(dev["id"])) 
                print ("windowopenmode{}.max   1"                                   .format(dev["id"])) 
                print ("windowopenmode{}.min   0"                                   .format(dev["id"])) 
                print ("windowopenmode{}.info Window Open Mode [{} - {}]"           .format(dev["id"], dev["model"], dev["identifier"]))

            if "summerActive" in dev:
                print ("summermode{}.label Summer Mode"                             .format(dev["id"])) 
                print ("summermode{}.type  GAUGE"                                   .format(dev["id"])) 
                print ("summermode{}.graph LINE"                                    .format(dev["id"])) 
                print ("summermode{}.max   1"                                       .format(dev["id"])) 
                print ("summermode{}.min   0"                                       .format(dev["id"])) 
                print ("summermode{}.info Summer Mode [{} - {}]"                    .format(dev["id"], dev["model"], dev["identifier"]))

            if "holidayActive" in dev:
                print ("holidaymode{}.label Holiday Mode"                           .format(dev["id"])) 
                print ("holidaymode{}.type  GAUGE"                                  .format(dev["id"])) 
                print ("holidaymode{}.graph LINE"                                   .format(dev["id"])) 
                print ("holidaymode{}.max   1"                                      .format(dev["id"])) 
                print ("holidaymode{}.min   0"                                      .format(dev["id"])) 
                print ("holidaymode{}.info Holiday Mode [{} - {}]"                  .format(dev["id"], dev["model"], dev["identifier"]))

        


    print("\n")
    print("multigraph battery")
    print("graph_title AVM Fritz!Box SmartHome Battery")
    print("graph_vlabel percent")
    print("graph_category smart home")
    print("graph_scale no")
    print("\n")


    for dev in simpleDevices:
        if dev["present"] and "batteryChargeLevelInPct" in dev:
            print ("battery{}.label {}"                                  .format(dev["id"], dev["displayName"])) 
            print ("battery{}.type GAUGE"                                .format(dev["id"])) 
            print ("battery{}.graph LINE"                                .format(dev["id"])) 
            print ("battery{}.max 100"                                   .format(dev["id"])) 
            print ("battery{}.min   0"                                   .format(dev["id"])) 
            print ("battery{}.warning 30:110"                            .format(dev["id"])) 
            print ("battery{}.critical 10:120"                           .format(dev["id"])) 
            print ("battery{}.info Battery [{} - {}]"                    .format(dev["id"], dev["model"], dev["identifier"]))



    print("\n")
    print("multigraph batterylow")
    print("graph_title AVM Fritz!Box SmartHome Battery Low Warning")
    print("graph_vlabel ok/warning")
    print("graph_category smart home")
    print("graph_scale no")
    print("\n")
    
    for dev in simpleDevices:
        if dev["present"] and "batteryLow" in dev:
            print ("batterylow{}.label {}"                               .format(dev["id"], dev["displayName"]))
            print ("batterylow{}.type GAUGE"                             .format(dev["id"])) 
            print ("batterylow{}.graph LINE"                             .format(dev["id"])) 
            print ("batterylow{}.max   1"                                .format(dev["id"])) 
            print ("batterylow{}.min   0"                                .format(dev["id"])) 
            print ("batterylow{}.warning  0.5"                           .format(dev["id"]))
            print ("batterylow{}.critical 1"                             .format(dev["id"]))
            print ("batterylow{}.info Battery Low Warning [{} - {}]"     .format(dev["id"], dev["model"], dev["identifier"]))


    print("\n")
    print("multigraph voltage")
    print("graph_title AVM Fritz!Box SmartHome Voltage")
    print("graph_vlabel Volt")
    print("graph_category smart home")
    print("graph_scale no")
    print("\n")
    
    for dev in simpleDevices:
        if dev["present"] and "voltageInVolt" in dev:
            print ("voltage{}.label {}"                                    .format(dev["id"], dev["displayName"]))
            print ("voltage{}.type GAUGE"                                  .format(dev["id"])) 
            print ("voltage{}.graph LINE"                                  .format(dev["id"])) 
            print ("voltage{}.min     0"                                   .format(dev["id"])) 
            print ("voltage{}.warning  220:240"                            .format(dev["id"])) 
            print ("voltage{}.critical 210:245"                            .format(dev["id"])) 
            print ("voltage{}.info Voltage [{} - {}]"                      .format(dev["id"], dev["model"], dev["identifier"]))



    print("\n")
    print("multigraph smarthome_power")
    print("graph_title AVM Fritz!Box SmartHome Power")
    print("graph_vlabel Watt")
    print("graph_category smart home")
    print("graph_scale no")

    powerIdList = [f'smarthome_power{dev["id"]}' for dev in simpleDevices if ( dev["present"] and "powerInWatt" in dev ) ]
    print("graph_order total_smarthome_power " + " ".join(powerIdList))

    print("\n")
    
    for dev in simpleDevices:
        if dev["present"] and "powerInWatt" in dev:
            print ("smarthome_power{}.label {}"                                    .format(dev["id"], dev["displayName"]))
            print ("smarthome_power{}.type GAUGE"                                  .format(dev["id"])) 
            print ("smarthome_power{}.graph LINE"                                  .format(dev["id"])) 
            print ("smarthome_power{}.min      0"                                  .format(dev["id"])) 
            print ("smarthome_power{}.warning  1500"                               .format(dev["id"])) 
            print ("smarthome_power{}.critical 2000"                               .format(dev["id"])) 
            print ("smarthome_power{}.info Power [{} - {}]"                        .format(dev["id"], dev["model"], dev["identifier"]))
        # end if
    # end if

                                           
    print(f"total_smarthome_power.label       total")
    print(f"total_smarthome_power.cdef        " + ",".join(powerIdList) + ",ADDNAN" * (len(powerIdList) - 1));
    print(f"total_smarthome_power.min         0")



    print("\n")
    print("multigraph smarthome_powerAvg")
    print("graph_title AVM Fritz!Box SmartHome Power Average (from Energy)")
    print("graph_vlabel W")
    print("graph_category smart home")
    print("graph_scale no")
                                           
    powerAvgIdList = [f'smarthome_powerAvg{dev["id"]}' for dev in simpleDevices if ( dev["present"] and "energyInKWH" in dev ) ]
    print("graph_order total_smarthome_powerAvg " + " ".join(powerAvgIdList))

    print("\n")
    
    for dev in simpleDevices:
        if dev["present"] and "energyInKWH" in dev:
            print ("smarthome_powerAvg{}.label {}"                                   .format(dev["id"], dev["displayName"]))
            print ("smarthome_powerAvg{}.type DERIVE"                                .format(dev["id"])) 
            print ("smarthome_powerAvg{}.graph LINE"                                 .format(dev["id"])) 
            print ("smarthome_powerAvg{}.min   0"                                    .format(dev["id"])) 
            print ("smarthome_powerAvg{}.info Power Average [{} - {}]"               .format(dev["id"], dev["model"], dev["identifier"]))
            
    print(f"total_smarthome_powerAvg.label       total")
    print(f"total_smarthome_powerAvg.cdef        " + ",".join(powerAvgIdList) + ",ADDNAN" * (len(powerAvgIdList) - 1));
    print(f"total_smarthome_powerAvg.min         0")


    print("\n")
    print("multigraph energy")
    print("graph_title AVM Fritz!Box SmartHome Energy")
    print("graph_vlabel kWh")
    print("graph_category smart home")
    print("graph_scale no")
                                           
    energyIdList = [f'energy{dev["id"]}' for dev in simpleDevices if ( dev["present"] and "energyInKWH" in dev ) ]
    print("graph_order total_energy " + " ".join(energyIdList))

    print("\n")
    
    for dev in simpleDevices:
        if dev["present"] and "energyInKWH" in dev:
            print ("energy{}.label {}"                                   .format(dev["id"], dev["displayName"]))
            print ("energy{}.type GAUGE"                                 .format(dev["id"])) 
            print ("energy{}.graph LINE"                                 .format(dev["id"])) 
            print ("energy{}.min   0"                                    .format(dev["id"])) 
            print ("energy{}.info Energy [{} - {}]"                      .format(dev["id"], dev["model"], dev["identifier"]))
            
    print(f"total_energy.label       total")
    print(f"total_energy.cdef        " + ",".join(energyIdList) + ",ADDNAN" * (len(energyIdList) - 1));
    print(f"total_energy.min         0")



    print("\n")
    print("multigraph smarthome_powerswitch")
    print("graph_title AVM Fritz!Box SmartHome Power Switch")
    print("graph_vlabel On/Off")
    print("graph_category smart home")
    print("graph_scale no")
    print("\n")
    
    for dev in simpleDevices:
        if dev["present"] and "powerSwitchOn" in dev:
            print ("smarthome_powerswitch{}.label {}"                              .format(dev["id"], dev["displayName"]))
            print ("smarthome_powerswitch{}.type GAUGE"                            .format(dev["id"])) 
            print ("smarthome_powerswitch{}.graph LINE"                            .format(dev["id"])) 
            print ("smarthome_powerswitch{}.min   0"                               .format(dev["id"])) 
            print ("smarthome_powerswitch{}.max   1"                               .format(dev["id"])) 
            print ("smarthome_powerswitch{}.info On/Off [{} - {}]"                 .format(dev["id"], dev["model"], dev["identifier"]))
    
            
    if os.environ.get('host_name'):
        print("host_name " + os.environ['host_name'])


if __name__ == '__main__':
    if len(sys.argv) == 2 and sys.argv[1] == 'config':
        devices = getDevices(debug = False)
        print_config(devices)
        if "MUNIN_CAP_DIRTYCONFIG" in os.environ and os.environ["MUNIN_CAP_DIRTYCONFIG"] == "1":
            print("")
            print_smart_home_measurements(devices, debug = False)
        # end if DIRTY CONFIG
    elif len(sys.argv) == 2 and sys.argv[1] == 'autoconf':
        print('yes')
    elif len(sys.argv) == 2 and sys.argv[1] == 'debug':
        devices = getDevices(debug = True)
        print_smart_home_measurements(devices, debug = True)
    elif len(sys.argv) == 1 or len(sys.argv) == 2 and sys.argv[1] == 'fetch':
        # Some docs say it'll be called with fetch, some say no arg at all
        try:
            devices = getDevices(debug = False)
            print_smart_home_measurements(devices, debug = False)
        except:
            sys.exit("Couldn't retrieve fritzbox smarthome data")

