﻿# -*- coding: utf-8 -*-
'''
@author:     look

@copyright:  1999-2020 Alibaba.com. All rights reserved.

@license:    Apache Software License 2.0

@contact:    390125133@qq.com
'''

'''FPS监控器
'''
import queue
import datetime
import time
import re
import threading
import os,sys
import copy
import csv
import traceback

BaseDir=os.path.dirname(__file__)
sys.path.append(os.path.join(BaseDir,'../..'))

from mobileperf.common.basemonitor import Monitor
from mobileperf.android.tools.androiddevice import AndroidDevice
from mobileperf.common.log import logger
from mobileperf.common.utils import TimeUtils
from mobileperf.android.globaldata import RuntimeData

class SurfaceStatsCollector(object):
    '''Collects surface stats for a SurfaceView from the output of SurfaceFlinger
    '''
    def __init__(self, device, frequency,package_name,fps_queue,jank_threshold,use_legacy = False):
        self.device = device
        self.frequency = frequency
        self.package_name = package_name
        self.jank_threshold = jank_threshold /1000.0    # 内部的时间戳是秒为单位
        self.use_legacy_method = use_legacy
        self.surface_before = 0
        self.last_timestamp = 0
        self.data_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.focus_window = None
#       queue 上报线程用
        self.fps_queue = fps_queue

    def start(self,start_time):
        '''打开SurfaceStatsCollector
        '''
        if not self.use_legacy_method and self._clear_surfaceflinger_latency_data():
            try:
                self.focus_window = self.get_focus_activity()
                # 如果self.focus_window里包含字符'$'，必须将其转义
                if (self.focus_window.find('$') != -1):
                    self.focus_window = self.focus_window.replace('$','\$')
            except:
                logger.warn(u'无法动态获取当前Activity名称，使用page_flip统计全屏帧率！')
                self.use_legacy_method = True
                self.surface_before = self._get_surface_stats_legacy()
        else:
            logger.debug("dumpsys SurfaceFlinger --latency-clear is none")
            self.use_legacy_method = True
            self.surface_before = self._get_surface_stats_legacy()
        self.collector_thread = threading.Thread(target=self._collector_thread)
        self.collector_thread.start()
        self.calculator_thread = threading.Thread(target=self._calculator_thread,args=(start_time,))
        self.calculator_thread.start()

    def stop(self):
        '''结束SurfaceStatsCollector
        '''
        if self.collector_thread:
            self.stop_event.set()
            self.collector_thread.join()
            self.collector_thread = None
            if self.fps_queue:
                self.fps_queue.task_done()

    def get_focus_activity(self):
        '''通过dumpsys window windows获取activity名称  window名?
        '''
        return self.device.adb.get_focus_activity()


    def _calculate_results(self, refresh_period, timestamps):
        """Returns a list of SurfaceStatsCollector.Result.
        不少手机第一列  第三列 数字完全相同
        """

        frame_count = len(timestamps)
        if frame_count ==0:
            fps = 0
            jank = 0
        elif frame_count == 1:
            fps = 1
            jank = 0
        else:
            seconds = timestamps[-1][1] - timestamps[0][1]
            if seconds > 0:
                fps = int(round((frame_count - 1) / seconds))
                jank =self._calculate_janky(timestamps)
            else:
                fps = 1
                jank = 0
        return fps,jank


    def _calculate_results_new(self, refresh_period, timestamps):
        """Returns a list of SurfaceStatsCollector.Result.
        不少手机第一列  第三列 数字完全相同
        """

        frame_count = len(timestamps)
        if frame_count ==0:
            fps = 0
            jank = 0
        elif frame_count == 1:
            fps = 1
            jank = 0
        elif frame_count == 2 or frame_count ==3 or frame_count==4:
            seconds = timestamps[-1][1] - timestamps[0][1]
            if seconds > 0:
                fps = int(round((frame_count - 1) / seconds))
                jank = self._calculate_janky(timestamps)
            else:
                fps = 1
                jank = 0
        else:
            seconds = timestamps[-1][1] - timestamps[0][1]
            if seconds > 0:
                fps = int(round((frame_count - 1) / seconds))
                jank =self._calculate_jankey_new(timestamps)
            else:
                fps = 1
                jank = 0
        return fps,jank


    def _calculate_jankey_new(self,timestamps):

        '''同时满足两个条件计算为一次卡顿：
            ①Display FrameTime>前三帧平均耗时2倍。
            ②Display FrameTime>两帧电影帧耗时 (1000ms/24*2≈83.33ms)。
            '''

        twofilmstamp = 83.3 / 1000.0
        tempstamp = 0
        # 统计丢帧卡顿
        
        jank = 0
        for index,timestamp in enumerate(timestamps):
            #前面四帧按超过166ms计算为卡顿
            if (index == 0) or (index == 1) or (index == 2) or (index == 3):
                if tempstamp == 0:
                    tempstamp = timestamp[1]
                    continue
                # 绘制帧耗时
                costtime = timestamp[1] - tempstamp
                # 耗时大于阈值10个时钟周期,用户能感受到卡顿感
                if costtime > self.jank_threshold:
                    jank = jank + 1
                tempstamp = timestamp[1]
            elif index > 3:
                currentstamp = timestamps[index][1]
                lastonestamp = timestamps[index - 1][1]
                lasttwostamp = timestamps[index - 2][1]
                lastthreestamp = timestamps[index - 3][1]
                lastfourstamp = timestamps[index - 4][1]
                tempframetime = ((lastthreestamp - lastfourstamp) + (lasttwostamp - lastthreestamp) + (
                        lastonestamp - lasttwostamp)) / 3 * 2
                currentframetime = currentstamp - lastonestamp
                if (currentframetime > tempframetime) and (currentframetime > twofilmstamp):
                    jank = jank + 1
        return jank


    def _calculate_janky(self,timestamps):
        tempstamp = 0
        #统计丢帧卡顿
        jank = 0
        for timestamp in timestamps:
            if tempstamp == 0:
                tempstamp = timestamp[1]
                continue
            #绘制帧耗时
            costtime = timestamp[1] - tempstamp
            #耗时大于阈值10个时钟周期,用户能感受到卡顿感
            if costtime > self.jank_threshold:
                jank = jank + 1
            tempstamp = timestamp[1]
        return jank

    def _calculator_thread(self,start_time):
        '''处理surfaceflinger数据
        '''
        fps_file = os.path.join(RuntimeData.package_save_path, 'fps.csv')
        if self.use_legacy_method:
            fps_title = ['datetime', 'fps']
        else:
            fps_title = ['datetime', "activity window", 'fps', 'jank']
        try:
            with open(fps_file, 'a+') as df:
                csv.writer(df, lineterminator='\n').writerow(fps_title)
                if self.fps_queue:
                    fps_file_dic = {'fps_file': fps_file}
                    self.fps_queue.put(fps_file_dic)
        except RuntimeError as e:
            logger.exception(e)

        while True:
            try:
                data = self.data_queue.get()
                if isinstance(data, str) and data == 'Stop':
                    break
                before = time.time()
                if self.use_legacy_method:
                    td = data['timestamp'] - self.surface_before['timestamp']
                    seconds = td.seconds + td.microseconds / 1e6
                    frame_count = (data['page_flip_count'] -
                                   self.surface_before['page_flip_count'])
                    fps = int(round(frame_count / seconds))
                    if fps>60:
                        fps = 60
                    self.surface_before = data
                    logger.debug('FPS:%2s'%fps)
                    tmp_list = [TimeUtils.getCurrentTimeUnderline(),fps]
                    try:
                        with open(fps_file, 'a+',encoding="utf-8") as f:
                            # tmp_list[0] = TimeUtils.formatTimeStamp(tmp_list[0])
                            csv.writer(f, lineterminator='\n').writerow(tmp_list)
                    except RuntimeError as e:
                        logger.exception(e)
                else:
                    refresh_period = data[0]
                    timestamps = data[1]
                    collect_time = data[2]
                    # fps,jank = self._calculate_results(refresh_period, timestamps)
                    fps, jank = self._calculate_results_new(refresh_period, timestamps)
                    logger.debug('FPS:%2s Jank:%s'%(fps,jank))
                    fps_list=[collect_time,self.focus_window,fps,jank]
                    if self.fps_queue:
                        self.fps_queue.put(fps_list)
                    if not self.fps_queue:#为了让单个脚本运行时保存数据
                        try:
                            with open(fps_file, 'a+',encoding="utf-8") as f:
                                tmp_list = copy.deepcopy(fps_list)
                                tmp_list[0] = TimeUtils.formatTimeStamp(tmp_list[0])
                                csv.writer(f, lineterminator='\n').writerow(tmp_list)
                        except RuntimeError as e:
                            logger.exception(e)
                time_consume = time.time() - before
                delta_inter = self.frequency - time_consume
                if delta_inter > 0:
                    time.sleep(delta_inter)
            except:
                logger.error("an exception hanpend in fps _calculator_thread ,reason unkown!")
                s = traceback.format_exc()
                logger.debug(s)
                if self.fps_queue:
                    self.fps_queue.task_done()

    def _collector_thread(self):
        '''收集surfaceflinger数据
                             用了两种方式:use_legacy_method 为ture时，需要root权限:
                             service call SurfaceFlinger 1013 得到帧数
                为false,dumpsys SurfaceFlinger --latency  
        Android 8.0 dumpsys SurfaceFlinger 没有内容
                则用dumpsys gfxinfo package_name framestats           
        '''
        is_first = True
        while not self.stop_event.is_set():
            try:
                before = time.time()
                if self.use_legacy_method:
                    surface_state = self._get_surface_stats_legacy()
                    if surface_state:
                        self.data_queue.put(surface_state)
                else:
                    timestamps = []
                    refresh_period, new_timestamps = self._get_surfaceflinger_frame_data()
                    if refresh_period is None or new_timestamps is None:
                        # activity发生变化，旧的activity不存时，取的时间戳为空，
                        self.focus_window = self.get_focus_activity()
                        logger.debug("refresh_period is None or timestamps is None")
                        continue
    #                计算不重复的帧
                    timestamps += [timestamp for timestamp in new_timestamps
                                                 if timestamp[1] > self.last_timestamp]
                    if len(timestamps):
                        first_timestamp = [[0, self.last_timestamp, 0]]
                        if not is_first:
                            timestamps = first_timestamp + timestamps
                        self.last_timestamp = timestamps[-1][1]
                        is_first = False
                    else:
                        # 两种情况：1）activity发生变化，但旧的activity仍然存时，取的时间戳不为空，但时间全部小于等于last_timestamp
                        #        2）activity没有发生变化，也没有任何刷新
                        is_first = True
                        cur_focus_window = self.get_focus_activity()
                        if self.focus_window !=  cur_focus_window:
                            self.focus_window = cur_focus_window
                            continue
                    logger.debug(timestamps)
                    self.data_queue.put((refresh_period, timestamps,time.time()))
                    time_consume = time.time() - before
                    delta_inter = self.frequency - time_consume
                    if delta_inter > 0:
                        time.sleep(delta_inter)
            except:
                logger.error("an exception hanpend in fps _collector_thread , reason unkown!")
                s = traceback.format_exc()
                logger.debug(s)
                if self.fps_queue:
                    self.fps_queue.task_done()
        self.data_queue.put(u'Stop')

    def _clear_surfaceflinger_latency_data(self):
        """Clears the SurfaceFlinger latency data.

        Returns:
            True if SurfaceFlinger latency is supported by the device, otherwise
            False.
        """
        # The command returns nothing if it is supported, otherwise returns many
        # lines of result just like 'dumpsys SurfaceFlinger'.
        if self.focus_window == None:
            results = self.device.adb.run_shell_cmd(
                'dumpsys SurfaceFlinger --latency-clear')
        else:
            results = self.device.adb.run_shell_cmd(
                'dumpsys SurfaceFlinger --latency-clear %s' % self.focus_window)
        return not len(results)

    def _get_surfaceflinger_frame_data(self):
        """Returns collected SurfaceFlinger frame timing data.
        return:(16.6,[[t1,t2,t3],[t4,t5,t6]])
        Returns:
            A tuple containing:
            - The display's nominal refresh period in seconds.
            - A list of timestamps signifying frame presentation times in seconds.
            The return value may be (None, None) if there was no data collected (for
            example, if the app was closed before the collector thread has finished).
        """
        # shell dumpsys SurfaceFlinger --latency <window name>
        # prints some information about the last 128 frames displayed in
        # that window.
        # The data returned looks like this:
        # 16954612
        # 7657467895508     7657482691352     7657493499756
        # 7657484466553     7657499645964     7657511077881
        # 7657500793457     7657516600576     7657527404785
        # (...)
        #
        # The first line is the refresh period (here 16.95 ms), it is followed
        # by 128 lines w/ 3 timestamps in nanosecond each:
        # A) when the app started to draw
        # B) the vsync immediately preceding SF submitting the frame to the h/w
        # C) timestamp immediately after SF submitted that frame to the h/w
        #
        # The difference between the 1st and 3rd timestamp is the frame-latency.
        # An interesting data is when the frame latency crosses a refresh period
        # boundary, this can be calculated this way:
        #
        # ceil((C - A) / refresh-period)
        #
        # (each time the number above changes, we have a "jank").
        # If this happens a lot during an animation, the animation appears
        # janky, even if it runs at 60 fps in average.
        #

# Google Pixel 2 android8.0 dumpsys SurfaceFlinger --latency结果
# 16666666
# 0       0       0
# 0       0       0
# 0       0       0
# 0       0       0
# 但华为 荣耀9 android8.0 dumpsys SurfaceFlinger --latency结果是正常的 但数据更新很慢  也不能用来计算fps
# 16666666
# 9223372036854775807     3618832932780   9223372036854775807
# 9223372036854775807     3618849592155   9223372036854775807
# 9223372036854775807     3618866251530   9223372036854775807

# Google Pixel 2 Android8.0 dumpsys SurfaceFlinger --latency window 结果
# C:\Users\luke01>adb -s HT7B81A05143 shell dumpsys SurfaceFlinger --latency window_name
# 16666666
        refresh_period = None
        timestamps = []
        nanoseconds_per_second = 1e9
        pending_fence_timestamp = (1 << 63) - 1
        if self.device.adb.get_sdk_version() >= 26:
            results = self.device.adb.run_shell_cmd(
                'dumpsys SurfaceFlinger --latency %s'%self.focus_window)
            results = results.replace("\r\n","\n").splitlines()
            refresh_period = int(results[0]) / nanoseconds_per_second
            results = self.device.adb.run_shell_cmd('dumpsys gfxinfo %s framestats'%self.package_name)
#             logger.debug(results)
#        把dumpsys gfxinfo package_name framestats的结果封装成   dumpsys SurfaceFlinger --latency的结果
# 方便后面计算fps jank统一处理
            results = results.replace("\r\n","\n").splitlines()
            if not len(results):
                return (None, None)
            isHaveFoundWindow = False
            PROFILEDATA_line = 0
            for line in results:
                if not isHaveFoundWindow:
                    if "Window" in line and self.focus_window in line:
                        isHaveFoundWindow = True
#                         logger.debug("Window line:"+line)
                if not isHaveFoundWindow:
                    continue
                if "PROFILEDATA" in line:
                    PROFILEDATA_line +=1
                fields = []
                fields = line.split(",")
                if fields and '0' == fields[0]:
#                     logger.debug(line)
# 获取INTENDED_VSYNC VSYNC FRAME_COMPLETED时间 利用VSYNC计算fps jank
                    timestamp = [int(fields[1]),int(fields[2]),int(fields[13])]
                    if timestamp[1] == pending_fence_timestamp:
                        continue
                    timestamp = [_timestamp / nanoseconds_per_second for _timestamp in timestamp]
                    timestamps.append(timestamp)
#               如果到了下一个窗口，退出
                if 2 == PROFILEDATA_line:
                    break
        else:
            results = self.device.adb.run_shell_cmd(
                'dumpsys SurfaceFlinger --latency %s'%self.focus_window)
            results = results.replace("\r\n","\n").splitlines()
            logger.debug("dumpsys SurfaceFlinger --latency result:")
            logger.debug(results)
            if not len(results):
                return (None, None)
            if not results[0].isdigit():
                return (None, None)
            try:
                refresh_period = int(results[0]) / nanoseconds_per_second
            except Exception as e:
                logger.exception(e)
                return (None, None)
            # If a fence associated with a frame is still pending when we query the
            # latency data, SurfaceFlinger gives the frame a timestamp of INT64_MAX.
            # Since we only care about completed frames, we will ignore any timestamps
            # with this value.

            for line in results[1:]:
                fields = line.split()
                if len(fields) != 3:
                    continue
                timestamp = [int(fields[0]),int(fields[1]),int(fields[2])]
                if timestamp[1] == pending_fence_timestamp:
                    continue
                timestamp = [_timestamp / nanoseconds_per_second for _timestamp in timestamp]
                timestamps.append(timestamp)
        return (refresh_period, timestamps)

    def _get_surface_stats_legacy(self):
        """Legacy method (before JellyBean), returns the current Surface index
             and timestamp.

        Calculate FPS by measuring the difference of Surface index returned by
        SurfaceFlinger in a period of time.

        Returns:
            Dict of {page_flip_count (or 0 if there was an error), timestamp}.
        """
        cur_surface = None
        timestamp = datetime.datetime.now()
        # 这个命令可能需要root
        ret = self.device.adb.run_shell_cmd("service call SurfaceFlinger 1013")
        if not ret :
            return None
        match = re.search('^Result: Parcel\((\w+)', ret)
        if match :
            cur_surface = int(match.group(1), 16)
            return {'page_flip_count': cur_surface,'timestamp': timestamp}
        return None

class FPSMonitor(Monitor):
    '''FPS监控器'''
    def __init__(self, device_id, package_name = None,frequency=1.0,timeout =24 * 60 * 60,fps_queue=None,jank_threshold=166, use_legacy = False):
        '''构造器
        
        :param str device_id: 设备id
        :param float frequency: 帧率统计频率，默认1秒
        :param int jank_threshold: 计算jank值的阈值，单位毫秒，默认10个时钟周期，166ms
        :param bool use_legacy: 当指定该参数为True时总是使用page_flip统计帧率，此时反映的是全屏内容的刷新帧率。
                    当不指定该参数时，对4.1以上的系统将统计当前获得焦点的Activity的刷新帧率
        '''
        self.use_legacy = use_legacy
        self.frequency = frequency  # 取样频率
        self.jank_threshold = jank_threshold
        self.device = AndroidDevice(device_id)
        self.timeout = timeout
        if not package_name:
            package_name = self.device.adb.get_foreground_process()
        self.package = package_name
        self.fpscollector = SurfaceStatsCollector(self.device, self.frequency, package_name,fps_queue,self.jank_threshold, self.use_legacy)


    def start(self,start_time):
        '''启动FPSMonitor日志监控器 
        '''
        if not RuntimeData.package_save_path:
            RuntimeData.package_save_path = os.path.join(os.path.abspath(os.path.join(os.getcwd(), "../..")),'results', self.package, start_time)
            if not os.path.exists(RuntimeData.package_save_path):
                os.makedirs(RuntimeData.package_save_path)
        self.start_time = start_time
        self.fpscollector.start(start_time)
        logger.debug('FPS monitor has start!')

    def stop(self):
        '''结束FPSMonitor日志监控器 
        '''
        self.fpscollector.stop()
        logger.debug('FPS monitor has stop!')

    def save(self):
        pass

    def parse(self, file_path):
        '''解析
        :param str file_path: 要解析数据文件的路径
        '''
        pass

    def get_fps_collector(self):
        '''获得fps收集器，收集器里保存着time fps jank的列表
        
        :return: fps收集器
        :rtype: SurfaceStatsCollector
        '''
        return self.fpscollector

if __name__ == '__main__':
#    tulanduo android8.0 api level 27
    monitor  = FPSMonitor('TC79SSDMO7HEY5Z9',"com.alibaba.ailabs.genie.smartapp",1)
#  mate 9 android8.0
#     monitor  = FPSMonitor('MKJNW18226007860',"com.sankuai.meituan",2)
# android8.0 Google Pixel 2
#     monitor  = FPSMonitor('HT7B81A05143',package_name = "com.alibaba.ailibs.genie.contacts",1)
    monitor.start(TimeUtils.getCurrentTimeUnderline())
    time.sleep(600)
    monitor.stop()

