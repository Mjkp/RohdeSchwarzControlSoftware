from RsInstrument import *
from os import write
import numpy as np
import time, signal, csv

class RsNGA:    
    def __init__(self,model,t_out=3000,logmode=False,mode = "OFF", debouncing = 1):
        self.power_supply_model = model
        self.time_out = t_out #3000 
        self.instr = None
        self.debounce = debouncing
        self.data = {"ch1":{"voltage":[],"current":[],"power":[],"seconds":[]},
                    "ch2":{"voltage":[],"current":[],"power":[],"seconds":[]}}
        self.channel_fusion_mode = mode
        self.plateau_y =[]
        self.platuau_x =[]
        self.derivative =None
        try:
            self.instr = RsInstrument(self.power_supply_model,True,False)
            RsInstrument.assert_minimum_version('1.14.0')
            self.instr.visa_timeout = self.time_out
            # for safety -> when the code is interrupted power supply should be off
            signal.signal(signal.SIGINT, self.keyboardInterruptHandler) 
        except ResourceError as e:
            print(e.args[0])
            print("mate, your power supply might be OFF or not connected to your PC")
            exit(1)
        # self.resetInstrument()


        # set log mode
        self.instr.instrument_status_checking = False
        self.instr.write_str('MY:MISSpelled:COMMand')
        self.instr.clear_status()
        self.instr.instrument_status_checking = True

        if(logmode):
            self.instr.logger.log_to_console = True
            self.instr.logger.mode = LoggingMode.On
        else:
            self.instr.logger.log_to_console = False
            self.instr.logger.mode = LoggingMode.Off

        self.setFusionMode(self.channel_fusion_mode)

    def resetInstrument(self):
        self.instr.reset()
        time.sleep(self.debounce*3) # it takes a while for the hardware to reset

    def setFusionMode(self,set_mode="OFF"):
        #NOTE if the output cables are not connected properly, the power supply will give hardware error, and you have to restart the device.
        fusion_mode = {"OFF": 'OUTP:FUS OFF',
                        "SERIES": 'OUTP:FUS SER',
                        "PARALLEL":'OUTP:FUS PAR'}
        self.instr.write_str_with_opc(fusion_mode[set_mode])
        time.sleep(self.debounce)       
        self.channel_fusion_mode = set_mode


    #close power supply
    def closePowerSupply(self):
        time.sleep(self.debounce)
        self.resetInstrument() # resets all the device setting, including the memories
        self.instr.close()

    def powerON(self):
        self.instr.write_str_with_opc('OUTP ON')

    def powerOFF(self):
        self.instr.write_str_with_opc('OUTP OFF')
    
    #get voltage
    def getVoltage(self, ch): 
        self.instr.write_str_with_opc(f'INST OUT{ch}')
        return float(self.instr.query_str('MEAS?'))
    
    #get current
    def getCurrent(self, ch):
        self.instr.write_str_with_opc(f'INST OUT{ch}')
        return float(self.instr.query_str_with_opc("MEAS:CURR?"))

    #get P val
    def getPower(self, ch):
        self.instr.write_str_with_opc(f'INST OUT{ch}')
        return float(self.instr.query_str_with_opc("MEAS:POW?"))

    #set voltage, current
    def setVoltageCurrent(self,v,i,ch,poweron=False,duration=0):
        # check the channel fusion modemode 
        '''
        #NOTE this will delay the hardware so it is best to check only once at the begining
        self.channel_fusion_mode = self.instr.query_str_with_opc("OUTP:FUS?")
        ch = 1 if self.channel_fusion_mode != "OFF" else ch_ # for serial and parallel channel is always 1
        '''
        self.instr.write_str_with_opc(f'INST OUT{ch}') # not using setFuseChannel function, since one might want to power the both channel at the same time
        self.instr.write_str_with_opc(f'APPLY "{v},{i}"')
        if(poweron):
            self.powerON()
            time.sleep(duration)
            if(duration>0):
                self.powerOFF()
        time.sleep(self.debounce)

    def detectPlateau(self,ch,tolerance=0.01, plat_distance=2, x = "seconds",y="power" ):
        import pandas as pd
        
        df = pd.DataFrame.from_dict(self.data[f"ch{ch}"])
        self.derivative  = np.diff(df[y]/df[x]) 
        self.plateua_y=[py for _,py in enumerate(list(self.derivative))if abs(py)<=tolerance]
        self.plateua_x=[px for px,py in enumerate(list(self.derivative))if abs(py)<=tolerance]
        if(len(self.plateua_x)>1): # if it starts to reach the plateau
            self.plat_d = self.plateua_x[-1]-self.plateua_x[0]
            if(self.plat_d >= plat_distance):
                print(f"plateau for {self.plat_d} seconds")
                return True
            else:
                print(f"plateau for {self.plat_d} seconds")
                return False
    
    # get all data
    def getAllData(self,ch):
        return self.getVoltage(ch) , self.getCurrent(ch), self.getPower(ch)

    def setFuseChannel(self, ch):
        self.instr.write_str_with_opc(f'INST OUT{ch}')
    
    def logData(self,max_v,max_i,duration,channel = 1,poweron = True,decimal = 3,stop_at_plateau = False,tolerance = 0.01,plat_distance = 3,dx ="seconds",dy="power", save_csv = False, file_name = "data"):
        self.channel_fusion_mode = self.instr.query_str_with_opc("OUTP:FUS?")
        ch = 1 if self.channel_fusion_mode != "OFF" else channel # for serial and parallel channel is always 1
        self.setVoltageCurrent(max_v,max_i,ch,poweron)
        start_time = int(time.time())
        prev_time = -1 # negative 1 since it has not started counting
        while (time.time()<(start_time+duration)):
            curr_time = int(time.time()-start_time)
            if(curr_time>prev_time):
                v,i,p = self.getAllData(ch)
                self.data[f"ch{ch}"]["voltage"].append(round(v,decimal))
                self.data[f"ch{ch}"]["current"].append(round(i,decimal))
                self.data[f"ch{ch}"]["power"].append(round(p,decimal))
                self.data[f"ch{ch}"]["seconds"].append(curr_time)
                if(len(self.data[f"ch{ch}"]["seconds"])>1): # after the data is accumulated
                    if(self.detectPlateau(ch,tolerance,plat_distance,dx,dy)):# checking plateau for every second
                        if(stop_at_plateau):
                            print("it has reached its plateau!")
                            break
                        else:
                            continue
                prev_time = curr_time
        self.powerOFF()
        if (save_csv): self.saveCSV(self.data[f"ch{ch}"],file_name)

    def keyboardInterruptHandler(self, signal, frame):
        print("!!KeyboardInterrupt has been caught. powering OFF the instrument, and resetting...!!")
        self.powerOFF()
        self.instr.close()
        self.saveCSV(self.data["ch1"],"auto-save")
        exit(0)
    
    def saveCSV(self,data,file_name= "data"):
        data_values = np.transpose(np.array(list(data.values())))
        with open(f"{file_name}.csv", 'w', newline='') as f:
            write = csv.writer(f)
            write.writerow(list(data.keys()))
            write.writerows(data_values)
        print(f"data saved as {file_name}.csv")
    
if __name__ == "__main__":
    POWER_DURATION =100 # in seconds
    CH = 1
    MAX_VOLTAGE = 200 
    MAX_CURRENT = 0.005 # in amps
    INSTR_DEBOUNCING = 1
    DECIMAL_VAL = 3
    MODEL = 'USB0::0x0AAD::0x0197::5601.8002k05-101076::INSTR'
    LOG = False
    INST_MODE = "SERIES"

    powersupply = RsNGA(MODEL,logmode=LOG,mode=INST_MODE,debouncing=INSTR_DEBOUNCING)
    powersupply.logData(MAX_VOLTAGE,MAX_CURRENT,POWER_DURATION,channel=CH,poweron=True,decimal =DECIMAL_VAL,stop_at_plateau=True,save_csv=True)
    # powersupply.saveCSV(powersupply.data["ch1"],"data_1")
    # powersupply.setVoltageCurrent(MAX_VOLTAGE,MAX_CURRENT,CH,poweron=True,duration=10)

    powersupply.instr.close()
