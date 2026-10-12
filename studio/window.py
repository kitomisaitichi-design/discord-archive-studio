"""Resize only a uniquely identified Edge/Chrome app window, never the host Codex window."""
import ctypes as C
import os


def set_mode(mode, port, saved):
    if os.name != 'nt' or mode not in ('full','compact','dock'):
        return {'native': False}
    user = C.WinDLL('user32', use_last_error=True)
    ptr = C.c_void_p
    class Rect(C.Structure):
        _fields_=[('left',C.c_long),('top',C.c_long),('right',C.c_long),('bottom',C.c_long)]
    class Monitor(C.Structure):
        _fields_=[('size',C.c_uint32),('rect',Rect),('work',Rect),('flags',C.c_uint32)]
    callback=C.WINFUNCTYPE(C.c_int,ptr,C.c_ssize_t)
    user.EnumWindows.argtypes=[callback,C.c_ssize_t]
    user.GetWindowTextW.argtypes=[ptr,C.c_wchar_p,C.c_int]
    user.GetClassNameW.argtypes=[ptr,C.c_wchar_p,C.c_int]
    user.IsWindowVisible.argtypes=[ptr]
    user.GetWindowRect.argtypes=[ptr,C.POINTER(Rect)]
    user.MonitorFromWindow.argtypes=[ptr,C.c_uint32];user.MonitorFromWindow.restype=ptr
    user.GetMonitorInfoW.argtypes=[ptr,C.POINTER(Monitor)]
    user.MoveWindow.argtypes=[ptr,C.c_int,C.c_int,C.c_int,C.c_int,C.c_int]
    user.SetWindowPos.argtypes=[ptr,ptr,C.c_int,C.c_int,C.c_int,C.c_int,C.c_uint32]
    matches=[]
    marker='Discord Archive Studio · '+str(port)
    @callback
    def collect(hwnd,unused):
        title,klass=C.create_unicode_buffer(1024),C.create_unicode_buffer(128)
        user.GetWindowTextW(hwnd,title,1024);user.GetClassNameW(hwnd,klass,128)
        if user.IsWindowVisible(hwnd) and klass.value=='Chrome_WidgetWin_1' and title.value.startswith(marker):
            matches.append(hwnd)
        return 1
    user.EnumWindows(collect,0)
    if len(matches)!=1:
        return {'native':False}
    hwnd=matches[0];rect=Rect();user.GetWindowRect(hwnd,C.byref(rect))
    monitor=Monitor();monitor.size=C.sizeof(monitor)
    if not user.GetMonitorInfoW(user.MonitorFromWindow(hwnd,2),C.byref(monitor)):
        return {'native':False}
    work=monitor.work
    if mode=='dock':
        if 'restore' not in saved:saved['restore']=(rect.left,rect.top,rect.right-rect.left,rect.bottom-rect.top)
        width,height=min(550,work.right-work.left),min(210,work.bottom-work.top)
        x,y=work.right-width-18,work.bottom-height-18
        user.SetWindowPos(hwnd,ptr(-1),0,0,0,0,0x13)
    elif mode=='compact':
        width,height=min(1040,work.right-work.left),min(940,work.bottom-work.top)
        x,y=work.left+(work.right-work.left-width)//2,work.top+(work.bottom-work.top-height)//2
        user.SetWindowPos(hwnd,ptr(-2),0,0,0,0,0x13)
    else:
        x,y,width,height=saved.pop('restore',(work.left+20,work.top+20,min(1480,work.right-work.left-40),min(1000,work.bottom-work.top-40)))
        user.SetWindowPos(hwnd,ptr(-2),0,0,0,0,0x13)
    user.MoveWindow(hwnd,x,y,width,height,1)
    return {'native':True,'width':width,'height':height}
