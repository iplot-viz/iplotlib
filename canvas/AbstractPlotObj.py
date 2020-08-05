import sys
import random
from abc import ABC, abstractmethod
from enum import Enum
from iterplot.data.AbstractDataAccess import DataObj,MetaObj,PulseObj,FieldObj
import iterplot.processing.processing as pr


class DrawStyle(Enum):
    default = 1
    stepWPrePt = 2
    stepWMidPt =3 
    stepWPostPt = 4


class basicElt():


    def __init__(self):
        self.signame = ""
        self.impl = None
        self.procname = None
        self.pulsenb = None
        self.startT = None
        self.endT = None
        self.err = ""
        self.appearance = {
        'color':'','linestyle':'', 'symbol':'','linewidth':'',
        'visible':True,'drawstyle':DrawStyle.default
        }
        ##contains information about host and proto
        self.dataAcc = None
        ##contains actual data
        self.dataArch = None
        self.x0 = 0
        self.x1 = 0
        
    def setElt(self,signame,procname,pulsenb,startT,endT):
        self.signame = signame
        self.procname = procname
        self.pulsenb = pulsenb
        self.startT = startT
        self.endT = endT
        self.x0 = self.startT
        self.x1 = self.endT

    def setDataAcc(self,dataAcc):
        self.dataAcc = dataAcc

    def updateHostInfo(self,host,port):
        if(self.dataAcc == None):
            return -1
        self.dataAcc.setHostInfo(host,port)
        return 0

    def updateTimeInfo(self,ts,te):
        if ts == 0:
            self.x0 = self.startT
            self.x1 = self.endT
        else:
            self.x0 = ts
            self.x1 = te

    def setAppearanceProp(self,prop,propval):
        ret = -1
        if prop in self.appearance.keys():
            print("found a prop %s with val %s"%(prop,propval))
            self.appearance[prop]=propval
            print("found a prop dct %s "%(self.appearance[prop]))
            ret = 0
        return ret

    def getStatus(self):
        return self.err

    def updateXlimit(self,x0,x1):
        self.x0=xo
        self.x1=x1


###class related to one plot
class AbstractPlotObj(ABC):


    def __init__(self):
        self.signals = [] 
        self.sigaxes = None
        self.firstCall = True
        self.nrows = 0
        self.ylimit = {'r':None,'l': None}
        self.xlimit = {'r':None,'l':None}
        self.ncols = 0
        self.index = 0
        self.plotPp = {'grid':False,'title':'','legend':'','xname':'','yname':''}
        self.setFormatter()

    def setPlotPp(self,propn,propv):
        ret = -1
        if self.plotPp[propn] != None:
            self.plotPp[propn] = propv
            ret = 0
        return ret

    def setYlimits(self,right=None,left=None):
        ret = -1
        self.ylimit['r'] = right
        self.ylimit['l'] = left
        ret = 0
        return ret

    def setXlimits(self,right=None,left=None):
        ret = -1
        self.xlimit['r'] = right
        self.xlimit['l'] = left
        ret = 0
        return ret

    @abstractmethod
    def applyPlotPp(self,ax1):
        pass

    def setAppearanceBySig(self,signame,propn,propv):
        ret = -1
        for i in range(len(self.signals)):
            if self.signals[i].signame == signame:
                ret=self.signals[i].setAppearanceProp(propn,propv)
        return ret

    def addVar(self,signame,hi,pulse=0,tsS=0,tsE=0,myproc=None):
        be = basicElt()
        be.setElt(signame,myproc,pulse,tsS,tsE)
        be.setDataAcc(hi.da)
        print(type(hi.da))
        be.updateHostInfo(hi.hname,hi.hport)
        self.signals.append(be)

    def updateTimeInfo(self,tsS,tsE):
        for i in range(len(self.signals)):
            self.signals[i].updateTimeInfo(tsS,tsE)

    def clearVars(self):
        self.signals.clear()

    def updateSigTs(self,x0,x1):
        for i  in range(len(self.signals)):
            self.signals[i].updateXlimit(x0,x1)

    def retrieveData(self,sigElt):
        sigElt.dataArch = sigElt.dataAcc.getData(sigElt.signame,sigElt.pulsenb,sigElt.x0,sigElt.x1)
        if(sigElt.dataArch.errcode == 0):
            sigElt.err="OK"
        else:
            sigElt.errful = sigElt.dataArch.errdesc
            sigElt.err = "Error"

    def retrieveAllDtata(self):
        for i in range(len(self.signals)):
            self.retrieveData(signals[i])

    @abstractmethod   
    def setPlotPosition(self,nr,nc,idx,plotCan):
        pass

    def applyProc(self):
        return

    def retrieveAllData(self):
        for i in range(len(self.signals)):
            self.retrieveData(self.signals[i])

    def getStatus(self):
        statuses = []
        sigAndStat = {}
        cnt = -1
        prevSig = None
        for i in range(len(self.signals)):
            if prevSig == self.signals[i].signame:
                currd = statuses[cnt]
                statuses[cnt] = currd+"|"+self.signals[i].pulsenb+":"+self.signals[i].err
            else:
                statuses.append(self.signals[i].pulsenb+":"+self.signals[i].err)
                cnt += 1
                prevSig = self.signals[i].signame
        return statuses   

    @abstractmethod
    def plotOnly(self,ax1):
        pass

    @abstractmethod    
    def fetchAndPlot(self,axA):
        pass

           
        
            
            

