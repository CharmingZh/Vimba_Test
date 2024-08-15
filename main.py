"""BSD 2-Clause License

Copyright (c) 2023, Allied Vision Technologies GmbH
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""
import sys
from typing import Optional
from queue import Queue
import cv2

from vmbpy import *

import time


# All frames will either be recorded in this format, or transformed to it before being displayed
opencv_display_format = PixelFormat.Bgr8


def print_preamble():
    print('///////////////////////////////////////////////////')
    print('/// VmbPy Asynchronous Grab with OpenCV Example ///')
    print('///////////////////////////////////////////////////\n')


def print_usage():
    print('Usage:')
    print('    python asynchronous_grab_opencv.py [camera_id]')
    print('    python asynchronous_grab_opencv.py [/h] [-h]')
    print()
    print('Parameters:')
    print('    camera_id   ID of the camera to use (using first camera if not specified)')
    print()


def abort(reason: str, return_code: int = 1, usage: bool = False):
    print(reason + '\n')

    if usage:
        print_usage()

    sys.exit(return_code)


def parse_args() -> Optional[str]:
    args = sys.argv[1:]
    argc = len(args)

    for arg in args:
        if arg in ('/h', '-h'):
            print_usage()
            sys.exit(0)

    if argc > 1:
        abort(reason="Invalid number of arguments. Abort.", return_code=2, usage=True)

    return None if argc == 0 else args[0]


def get_camera(camera_id: Optional[str]) -> Camera:
    with VmbSystem.get_instance() as vmb:
        if camera_id:
            try:
                return vmb.get_camera_by_id(camera_id)

            except VmbCameraError:
                abort('Failed to access Camera \'{}\'. Abort.'.format(camera_id))

        else:
            cams = vmb.get_all_cameras()
            if not cams:
                abort('No Cameras accessible. Abort.')

            return cams[0]


def setup_camera(cam: Camera):
    with cam:
        # Enable auto exposure time setting if camera supports it
        try:
            cam.ExposureAuto.set('Continuous')

        except (AttributeError, VmbFeatureError):
            pass



        # Enable white balancing if camera supports it
        try:
            cam.BalanceWhiteAuto.set('Continuous')

        except (AttributeError, VmbFeatureError):
            pass

        # Try to adjust GeV packet size. This Feature is only available for GigE - Cameras.
        try:
            stream = cam.get_streams()[0]
            stream.GVSPAdjustPacketSize.run()
            while not stream.GVSPAdjustPacketSize.is_done():
                pass

        except (AttributeError, VmbFeatureError):
            pass


def setup_pixel_format(cam: Camera):
    # Query available pixel formats. Prefer color formats over monochrome formats
    cam_formats = cam.get_pixel_formats()
    cam_color_formats = intersect_pixel_formats(cam_formats, COLOR_PIXEL_FORMATS)
    convertible_color_formats = tuple(f for f in cam_color_formats
                                      if opencv_display_format in f.get_convertible_formats())

    cam_mono_formats = intersect_pixel_formats(cam_formats, MONO_PIXEL_FORMATS)
    convertible_mono_formats = tuple(f for f in cam_mono_formats
                                     if opencv_display_format in f.get_convertible_formats())

    # if OpenCV compatible color format is supported directly, use that
    if opencv_display_format in cam_formats:
        cam.set_pixel_format(opencv_display_format)

    # else if existing color format can be converted to OpenCV format do that
    elif convertible_color_formats:
        cam.set_pixel_format(convertible_color_formats[0])

    # fall back to a mono format that can be converted
    elif convertible_mono_formats:
        cam.set_pixel_format(convertible_mono_formats[0])

    else:
        abort('Camera does not support an OpenCV compatible format. Abort.')


class Handler:
    def __init__(self):
        self.display_queue = Queue(10)
        self.frame_count = 0
        self.start_time = time.time()

    def get_image(self):
        return self.display_queue.get(True)

    def __call__(self, cam: Camera, stream: Stream, frame: Frame):
        if frame.get_status() == FrameStatus.Complete:
            print('{} acquired {}'.format(cam, frame), flush=True)

            # Convert frame if it is not already the correct format
            if frame.get_pixel_format() == opencv_display_format:
                display = frame
            else:
                display = frame.convert_pixel_format(opencv_display_format)

            self.display_queue.put(display.as_opencv_image(), True)

            # Increment frame count
            self.frame_count += 1

            # Calculate and display frame rate every second
            current_time = time.time()
            elapsed_time = current_time - self.start_time

            if elapsed_time >= 1.0:  # Every second
                frame_rate = self.frame_count / elapsed_time
                print(f'Current Frame Rate: {frame_rate:.2f} FPS')
                # Reset for the next second
                self.frame_count = 0
                self.start_time = current_time

        cam.queue_frame(frame)


def main():
    print_preamble()
    cam_id = parse_args()

    with VmbSystem.get_instance():
        with get_camera(cam_id) as cam:
            setup_camera(cam)
            setup_pixel_format(cam)
            handler = Handler()

            try:
                cam.start_streaming(handler=handler, buffer_count=10)

                msg = 'Stream from \'{}\'. Press <Enter> to stop stream.'
                ENTER_KEY_CODE = 13

                last_frame_time = time.time()  # 记录上次显示帧的时间
                target_fps = 30
                frame_duration = 1.0 / target_fps  # 计算每帧的持续时间

                while True:
                    key = cv2.waitKey(1)
                    if key == ENTER_KEY_CODE:
                        cv2.destroyWindow(msg.format(cam.get_name()))
                        break

                    display = handler.get_image()

                    # 在窗口中显示帧率
                    current_time = time.time()
                    elapsed_time = current_time - handler.start_time

                    # 计算帧率时避免除以零
                    if elapsed_time > 0:  # 确保 elapsed_time 大于零
                        frame_rate = handler.frame_count / elapsed_time
                    else:
                        frame_rate = 0  # 如果 elapsed_time 为零，则帧率设为 0

                    # 更新帧计数
                    handler.frame_count += 1

                    # 每秒更新显示的帧率
                    if elapsed_time >= 1.0:
                        handler.frame_count = 0  # 重置帧计数
                        handler.start_time = current_time  # 更新开始时间

                    # 在图像上绘制帧率
                    cv2.putText(display, f'FPS: {frame_rate:.2f}', (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1,
                                (255, 255, 255), 2)

                    # 计算当前时间与上次帧的时间差
                    time_since_last_frame = time.time() - last_frame_time

                    # 如果时间差小于每帧持续时间，等待剩余的时间
                    if time_since_last_frame < frame_duration:
                        wait_time = int((frame_duration - time_since_last_frame) * 1000)  # 转换为毫秒
                        cv2.waitKey(wait_time)

                    # 更新上次帧的时间
                    last_frame_time = time.time()
                    cv2.imshow(msg.format(cam.get_name()), display)

            finally:
                cam.stop_streaming()


if __name__ == '__main__':
    main()
