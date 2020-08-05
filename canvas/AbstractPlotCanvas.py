"""
Abstract class which acts as an interface definition of the canvas/window plotting library.
it shall define all methods necessary to implement the application tools for data viz and analysis
"""


import sys
import random
import time
import math as mt
from abc import ABC, abstractmethod
import numpy as np
import iterplot.data.DAFactory as daf
import iterplot.processing.processing as pr
import iterplot.canvas.AbstractPlotObj as pl


class HostInfo():
    """
    class which contains information about the data source server
    """


    def __init__(self,parent=None):
        self.hname = None
        self.hport = None
        self.impl = None
        self.da = None
        
    def setHi(self,hname,hport,impl):
        """ 
            set host name , port name and type of implementation
            implementation will allow data source detection
        """
        self.hname = hname
        self.hport = hport
        self.impl = impl

    def setDa(self,da):
        """
            set the data factory
            allow to not depend on a specific impl
        """
        self.da = da

    def connectDa(self):
        """ connect to a data source """
        self.da.connect(self.hname,self.hport)


class AbstractPlotCanvas(ABC):
    """
        Abstract class that acts an interface to canvas
        It provides necessary methods to interact with canvas
    """

    def __init__(self,parent=None):
        self.plotFullIdx = 0
        self.textPP = (
            'fontsize','color','visible','fontname',
            'fontstyle','pos_x','pos_y'
            )
        self.onPress = 0
        self.between2click = 0
        self.firstCall = True
        self.zoomMode = 0
        self.daF = daf.DAFactory()
        self.pls = []
        self.nrows = 0
        self.ncols = 0
        self.ntot = 0
        self.currpi = 0
        # dims within a canvas
        self.cdims = {
            'wspace':0.2,'chspace':0.2,'cleft':0.125,
            'cright':0.9,'cbottom':0.1,'ctop':0.9
            }
        self.__cdimsdef = {
            'wspace':0.2,'chspace':0.2,'cleft':0.125,
            'cright':0.9,'cbottom':0.1,'ctop':0.9
            }
        self.axSet = []
        self.multi = None
        self.cfm = None
        self.currMouse = 'Select'
        self.shareXaxis = False
        self.firstCallMulti = True
        self.firstCallME = True
        self.fullmode = 0
        self.lastdbck = 0
        self.title = ""
        # 5 sec 
        self.minclickdist = 5
        self.serverList = {}

    def setSquareSize(self,ntotals):
        i = 1
        j = 1
        while (ntotals > j):
            i = i+1
            j = i*i
        self.ncols = i
        self.nrows = i
        self.ntot = ntotals

    def addNewDS(self,impl,hostname,port,aliass):
        hi = HostInfo()
        hi.setHi(hostname,port,impl)
        da = self.daF.getDA(impl)
        if da == None:
            return -1
        hi.setDa(da)
        hi.connectDa()
        if aliass == None or len(aliass) < 1:
            aliasX = hostname + "_" + str(port)
        else:
            aliasX = aliass
        self.serverList[aliass] = hi
        return 0

    def removeDS(self,alias):
        del self.serverList[alias]

    def getTextProp(self):
        return self.textPP

    def setRectSize(self,nr,nc,nt):
        self.ncols = nc
        self.nrows = nr
        self.ntot = nt

    def setShareXAxis(self,val=False):
        self.shareXAxis = val

    def initLayout(self,ntotals,nr=7,nc=5,shareX=False):
        print(shareX)
        if shareX == True:
            self.shareXaxis = True
            self.setRectSize(nr,nc,ntotals)
            print("ntotals=%d,nc=%d,nr=%d"%(self.ntot,self.nrows,self.ncols))
            return
        if nr > 0 and nc > 0:
            self.setRectSize(nr,nc,ntotals)
        else:
            self.setSquareSize(ntotals)
        print("ntotals=%d,nc=%d,nr=%d"%(self.ntot,self.nrows,self.ncols))
        #for i in range(self.ntot):
         #   self.axSet.append(self.figure.add_subplot(self.nrows,self.ncols,i+1))
     
    def appendVariables(self,signame,pulsenb,tsS,tsE,isnew,transform,hialias):
        if hialias not in self.serverList.keys():
            return -1
        return self.appendVariablesInt(signame,pulsenb,tsS,tsE,isnew,
        transform,self.serverList[hialias])

    @abstractmethod
    def appendVariablesInt(self,signame,pulsenb,tsS,tsE,isnew,transform,da):
        pass
    
    @abstractmethod
    def adjustDimBetweenPlots(self):
        pass

    def restoreDefaultDims(self):
        for k,v in self.__cdimsdef.items():
            self.cdims[k] = v

    @abstractmethod
    def setAppearanceByIdx(self,plot_idx,signame,propn,propv):
        pass
    
    @abstractmethod
    def setPlotPpByIdx(self,plot_idx,propn,propv):
        pass

    @abstractmethod
    def displayTitle(self,**kwargs):
        pass

    def setTitle(self,title,**kwargs):
        self.ctitle = title
        self.displayTitle(**kwargs)

    @abstractmethod
    def clearPlots(self,isreset=False):
        pass

    def clearAllVar(self):
        self.pls.clear()
        self.currpi = 0

    @abstractmethod
    def FetchAndPlotD(self):
        pass

    def getSignalStatuses(self):
        result = []
        for i in range(len(self.pls)):
            rtemp = self.pls[i].getStatus()
            result.extend(rtemp)
        return result

    @abstractmethod
    def enableMouseEvents(self):
        pass

    @abstractmethod
    def enableMultiCursor(self,ax,curshdler):
        pass

    @abstractmethod
    def clearMouseEvents(self):
        pass

    def resetPlot(self,cursh,allElt=False):
        pass

    def setMouseMode(self,val):
        self.currMouse=val
        if val == 'CrossHair':
            if self.fullmode == 1:
                self.enableCrosshair(True,self.cfm)
            else:
                self.enableCrosshair(True,self.multi)
        else:
            if self.fullmode == 1:
                self.enableCrosshair(False,self.cfm)
            else:
                self.enableCrosshair(False,self.multi)
        print (self.multi.visible)    

    @abstractmethod
    def enableCrosshair(self,val,curs):
        pass
            
    def findAxes(self,ax):
        for i in range(len(self.axSet)):
            if(self.axSet[i] == ax):
                return i
        return -1

    def onpress(self,event):
        print ("onpress call %s"%(self.currMouse))
        if self.currMouse == 'Zoom':
            self.zoomPress(event)
        if self.currMouse == 'Select':
            print ("on press select")
            self.selectPress(event)

        #print(event.inaxes)
        #i=self.findAxes(event.inaxes)
        #print("on press axes is %d",i)
    @abstractmethod
    def plotFullMode(self,i):
        pass

    @abstractmethod
    def selectPress(self,event):
        pass

    @abstractmethod
    def zoomFullMode(self,event,isFull):
        pass

    @abstractmethod
    def zoomPress(self,event):
        pass

    def updateSigTs(self,t1,t2):
        for i in range(len(self.pls)):
            self.pls[i].updateTimeInfo(t1,t2)
    
    def onrelease(self,event):
        if self.currMouse == 'Zoom':
            self.zoomRelease(event)

    @abstractmethod
    def zoomRelease(self,event):
        pass            

    def onmotion(self,event):
        if self.currMouse == 'Zoom':
            self.zoomMotion(event)

    @abstractmethod
    def zoomMotion(self,event):
        pass
