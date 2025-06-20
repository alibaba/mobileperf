#encoding:utf-8
'''
@description: 广告监控器

@author:     wangjiaqiang

@Copyright (c) 2014-2025 Zuoyebang, All rights reserved

@license:    Apache Software License 2.0

@contact:    187215129@qq.com
'''

import os
import sys
import threading
import time

BaseDir=os.path.dirname(__file__)
sys.path.append(os.path.join(BaseDir,'../..'))
from mobileperf.common.log import logger
from mobileperf.android.tools.androiddevice import AndroidDevice


class AdMonitor(object):
    def __init__(self, device_id, package, interval=1.0, timeout=24*60*60, ad_queue=None):
        self.device = AndroidDevice(device_id)
        self.package = package
        self._interval = interval
        self._timeout = timeout
        self._stop_event = threading.Event()
        self.ad_queue = ad_queue
        self._start_time = None
        self.collect_ad_thread = None
    
    def start(self, start_time):
        logger.debug("INFO: AdMonitor has started...")
        self._start_time = start_time
        self.enable_app_test_mode()
        self.collect_ad_thread = threading.Thread(target=self._collect_ad_thread, args=(start_time,))
        self.collect_ad_thread.start()

    def stop(self):
        logger.debug("INFO: AdMonitor has stopped...")
        if self.collect_ad_thread:
            self._stop_event.set()
            self.disable_app_test_mode()
            self.collect_ad_thread.join(timeout=1)
            self.collect_ad_thread = None
            #结束的时候，发送一个任务完成的信号，以结束队列
            if self.ad_queue:
                self.ad_queue.task_done()
        
    def _collect_ad_thread(self, start_time):
        """每10秒执行一次关闭广告的操作
        
        Args:
            start_time: 开始时间
        """
        logger.debug("INFO: Ad closing thread started...")
        end_time = time.time() + self._timeout
        # 计算运行时间，不超过timeout
        while not self._stop_event.is_set() and time.time() < end_time:
            try:
                # 执行关闭广告的adb命令
                cmd = 'am broadcast -a "com.zuoyebang.TestManagerReceiver.HIDE_AD" -n ai.socialapps.speakmaster/com.zuoyebang.appfactory.test.TestManagerReceiver'
                result = self.device.adb.run_shell_cmd(cmd)
                logger.debug(f"INFO: Executed ad closing command, result: {result}")
                
                # 等待10秒，如果在此期间收到停止信号则退出
                if self._stop_event.wait(10):
                    break
            except Exception as e:
                logger.error(f"ERROR: Failed to execute ad closing command: {str(e)}")
                # 发生异常时也等待10秒再继续
                if self._stop_event.wait(10):
                    break
        
        logger.debug("INFO: Ad closing thread finished")

    def enable_app_test_mode(self):
        """
        启用app测试模式
        """
        logger.debug("INFO: Enabling app test mode...")
        self.device.adb.run_shell_cmd('am broadcast -a "com.zuoyebang.TestManagerReceiver.SET_ENABLE" -n ai.socialapps.speakmaster/com.zuoyebang.appfactory.test.TestManagerReceiver --ez "enable" "true"')
        logger.debug("INFO: App test mode enabled")

    def disable_app_test_mode(self):
        """
        禁用app测试模式
        """
        logger.debug("INFO: Disabling app test mode...")
        self.device.adb.run_shell_cmd('am broadcast -a "com.zuoyebang.TestManagerReceiver.SET_ENABLE" -n ai.socialapps.speakmaster/com.zuoyebang.appfactory.test.TestManagerReceiver --ez "enable" "false"')
        logger.debug("INFO: App test mode disabled")
        