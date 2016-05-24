
from fe65p2.scan_base import ScanBase
import fe65p2.plotting as  plotting
import time

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - [%(levelname)-8s] (%(threadName)-10s) %(message)s")

import numpy as np
import bitarray
import tables as tb
from bokeh.charts import output_file, show, vplot, hplot, save
from progressbar import ProgressBar
import os

local_configuration = {
    "mask_steps": 1,
    "repeat_command": 99999
}

class TimewalkScan(ScanBase):
    scan_id = "timewalk_scan"

    def scan(self, mask_steps=1, repeat_command=1e6, columns = [True] + [False]*15, **kwargs):
        '''Scan loop

        Parameters
        ----------
        mask : int
            Number of mask steps.
        repeat : int
            Number of injections.
        '''

        self.dut['INJ_LO'].set_voltage(0.85, unit='V')
        self.dut['INJ_HI'].set_voltage(1.0, unit='V')

        self.dut['global_conf']['PrmpVbpDac'] = 80	#Preamp Follower bias
        self.dut['global_conf']['vthin1Dac'] = 255 	# "Pos discr threshold
        self.dut['global_conf']['vthin2Dac'] = 0	# Neg discr threshold
        self.dut['global_conf']['vffDac'] = 30		# Preamp feedback bias (def 42)
        self.dut['global_conf']['PrmpVbnFolDac'] = 51	#Preamp Follower bias (def 51)
        self.dut['global_conf']['vbnLccDac'] = 1		#Leakage current compensation (def 1)
        self.dut['global_conf']['compVbnDac'] = 25		#Comp. bias (def. 25)
        self.dut['global_conf']['preCompVbnDac'] = 50	#Precomp. bias (def 50)

        self.dut.write_global()

        #write InjEnLd & PixConfLd to '1
        self.dut['pixel_conf'].setall(True)
        self.dut.write_pixel_col()
        self.dut['global_conf']['SignLd'] = 1			#Selects pos/neg disc TDAC value
        self.dut['global_conf']['InjEnLd'] = 1			#enables analog injection
        self.dut['global_conf']['TDacLd'] = 0b1111		#TDAC value to be selected with SignLdCnfg
        self.dut['global_conf']['PixConfLd'] = 0b11		#Hit HitOrEn/HitOr/PowerOn see table
        self.dut.write_global()

        #write SignLd & TDacLd to '0
        self.dut['pixel_conf'].setall(False)
        self.dut.write_pixel_col()
        self.dut['global_conf']['SignLd'] = 1
        self.dut['global_conf']['InjEnLd'] = 1
        self.dut['global_conf']['TDacLd'] = 0b1000
        self.dut['global_conf']['PixConfLd'] = 0b00
        self.dut.write_global()

        #test hit
        self.dut['global_conf']['TestHit'] = 0 #Enables digital injection via LD_CNFG pin
        self.dut['global_conf']['SignLd'] = 0
        self.dut['global_conf']['InjEnLd'] = 0
        self.dut['global_conf']['TDacLd'] = 0
        self.dut['global_conf']['PixConfLd'] = 0

#        self.dut['global_conf']['OneSr'] = 0 #All SR chained together (4096 bit), overwrites ColSrEnCnfg
        self.dut['global_conf']['ColEn'][:] = bitarray.bitarray(columns)  #Enables column (If '0' col does not receive clk, trigger, etc)
        self.dut.write_global()

        self.dut['control']['RESET'] = 0b01
        self.dut['control']['DISABLE_LD'] = 0
        self.dut['control'].write()

        self.dut['control']['CLK_OUT_GATE'] = 1
        self.dut['control']['CLK_BX_GATE'] = 1
        self.dut['control'].write()
        time.sleep(0.1)

        self.dut['control']['RESET'] = 0b11
        self.dut['control'].write()

        #enable inj pulse and trigger
        wiat_for_read = (16 + columns.count(True) * (4*64/mask_steps) * 2 ) * (20/2) + 100
        self.dut['inj'].set_delay(wiat_for_read)
        self.dut['inj'].set_width(10) #100
        self.dut['inj'].set_repeat(99999)
        self.dut['inj'].set_en(False) #False

        self.dut['trigger'].set_delay(400-4)       #400-4
        self.dut['trigger'].set_width(16)
        self.dut['trigger'].set_repeat(1)
        self.dut['trigger'].set_en(False)

        logging.debug('Enable TDC')
        self.dut['tdc'].ENABLE = 1

        #lmask = [0]*64 + [0]*32 + [1] +[0]*31 + [0]*3968 #only the 32nd px of the 2nd col should fire.

        lmask = 4067*[0]+[1]+28*[0]
        print len(lmask)
        bv_mask = bitarray.bitarray(lmask)
        with self.readout():
            #pbar = ProgressBar(maxval=mask_steps).start()

            self.dut['global_conf']['vthin1Dac'] = 255
            self.dut.write_global()
            #set all InjEn to 0
            self.dut['pixel_conf'].setall(False)
            self.dut.write_pixel_col()
            self.dut['global_conf']['InjEnLd'] = 1 			#enables analog injection
            self.dut['global_conf']['PixConfLd'] = 0b00
            self.dut.write_global()

            self.dut['pixel_conf'][:] = bv_mask
            self.dut.write_pixel_col()
            self.dut['global_conf']['PixConfLd'] = 0b11
            self.dut['global_conf']['InjEnLd'] = 1
            self.dut.write_global()


            bv_mask[1:] = bv_mask[0:-1]
            bv_mask[0] = 0

            self.dut['global_conf']['vthin1Dac'] = 20  #global threshold ctrl 1
            self.dut.write_global()

            self.dut['inj'].start()

            if os.environ.get('TRAVIS'):
                logging.debug('.')

            #pbar.update(i)

            while not self.dut['inj'].is_done():
                pass

            while not self.dut['trigger'].is_done():
                pass


        #self.fifo_readout.print_readout_status()

            #just some time for last read
            self.dut['trigger'].set_en(False)
            self.dut['inj'].start()

    def analyze(self):
        h5_filename = self.output_filename +'.h5'

        with tb.open_file(h5_filename, 'r+') as in_file_h5:
            raw_data = in_file_h5.root.raw_data[:]
            meta_data = in_file_h5.root.meta_data[:]

            hit_data = self.dut.interpret_raw_data(raw_data, meta_data)
            in_file_h5.createTable(in_file_h5.root, 'hit_data', hit_data, filters=self.filter_tables)

        occ_plot, H = plotting.plot_occupancy(h5_filename)
        tot_plot,_ = plotting.plot_tot_dist(h5_filename)
        lv1id_plot, _ = plotting.plot_lv1id_dist(h5_filename)

        output_file(self.output_filename + '.html', title=self.run_name)
        save(vplot(occ_plot, tot_plot, lv1id_plot))

        return H

if __name__ == "__main__":

    scan = TimewalkScan()
    scan.start(**local_configuration)
    scan.analyze()
