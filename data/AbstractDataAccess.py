import sys
from abc import ABC, abstractmethod
import uda_client_reader_python as uc


class PulseObj():


    def __init__(self,parent=None):
        self.pulsenb=None
        self.startTime=0
        self.endTime=0
        self.description=None
        self.pstatus=None
        self.errcode=0
        self.errdesc=""

    def setPulseInfo(self,pnb,pTs,pTe,pde=None,pst=None):
        self.pulsenb=pnb
        self.startTime=pTs
        self.endTime=pTe
        self.description=pde
        self.pstatus=pst

    def clearInfo(self,err=False):
        self.pulsenb=None
        self.startTime=0
        self.endTime=0
        self.description=None
        self.pstatus=None
        if err==True:
            self.errcode=0
            self.errdesc=""

    def setErr(self,errc,errd):
        self.errcode=errc
        self.errdesc=errd


class MetaObj():
    def __init__(self,parent=None):
        self.mname=None
        self.mdesc=None
        self.mval=None
        self.munit=None
        self.errcode=0
        self.errdesc=""

    def setMinfo(self,name,val,unit=None,desc=None):
        self.mname=name
        self.mdesc=desc
        self.munit=unit
        self.mval=val

    def clearMeta(self,err=True):
        self.mname=None
        self.mdesc=None
        self.mval=None
        self.munit=None
        if  err==True: 
            self.errcode=0
            self.errdesc=""

    def setErr(self,errc,errd):
        self.errcode=errc
        self.errdesc=errd


class FieldObj():


    def __init__(self,parent=None):
        self.fname=None
        self.ftype=None
        self.funit=None
        self.fdesc=None

    def setErr(self,errc,errd):
        self.errcode=0
        self.errdesc=""

    def setFInfo(self,name,typef,unit=None,desc=None):
        self.fname=name
        self.ftype=typef
        self.funit=unit
        self.fdesc=desc

    def clearField(self,err=True):
        self.fname=None
        self.ftype=None
        self.funit=None
        self.desc=None
        if err == True:
            self.errc = 0
            self.errdesc = ""


class DataObj():


    def __init__(self,parent=None):
        self.xtype=""
        self.ytype=""
        self.xlabel=""
        self.ylabel=""
        self.xunit =""
        self.yunit =""
        self.xdata=None
        self.ydata=None
        self.drank=""
        self.errcode=0
        self.errdesc = ""

    def setA(self,xtype,ytype,xlabel,ylabel,xunit,yunit,drank):
        self.xtype=xtype
        self.ytype=ytype
        self.xlabel=xlabel
        self.ylabel=ylabel
        self.xunit=xunit
        self.yunit=yunit
        self.drank=drank
        self.errcode=0
        self.errdesc=""

    def setData(self,data,dtype,myprocList=None,myprocName=None):
        if dtype == 1 :
            
            self.xdata=data
        else:
            self.ydata=data
            #if myprocList!=None and myprocName!=None:
             #   self.xdata=myprocList[myprocName])

    def clearData(self,err=True):
        self.xtype =""
        self.ytype =""
        self.xlabel =""
        self.ylabel =""
        self.xunit =""
        self.yunit =""
        self.xdata=None
        self.ydata=None
        self.drank=""
        if err==True:
            self.errcode=0
            self.errdesc=""

    def setErr(self,errc,errd):
        self.errcode=errc
        self.errdesc=errd


###class to interface with data source - here UDA
class ADataAccess(ABC):


    def __init__(self,parent=None):
        self.shost = None
        self.sport = None
        self.errcode = 0
        self.errdesc = ""
        self.UCR = None
        self.connected = False
    
    def setHostInfo(self,hostname,port):
        self.shost = hostname
        self.sport = port

    @abstractmethod
    def connect(self,udah="localhost",port=3090):
        pass

    def isConnected(self):
        if (self.connected == True):
            return True
        else:
            return False

    @abstractmethod ##must return a dataobj
    def getData(self,varname="",pulsenb=0,tsS=0,tsE=0,
    nbpoints=1000,myprocList=None,myprocName=None):
        pass

    @abstractmethod
    def resetConn(self):
        pass
    
    @abstractmethod ##return list of key value/pair with data type and unit
    def getMetadata(self,varname="",timestamp=0):
        pass
    
    @abstractmethod ##return a list of (pulse nb, startT,endTime,description,status)
    def getPulses(self):
        pass

    @abstractmethod
    def getVarFields(self,varname="",timestamp=0):
        pass

    
