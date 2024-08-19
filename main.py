import sys
import time
import threading
from typing import Optional
from queue import Queue
import cv2
from vmbpy import *

# All frames will either be recorded in this format, or transformed to it before being displayed
opencv_display_format = PixelFormat.Bgr8


def abort(reason: str, return_code: int = 1, usage: bool = False):
    # print(reason + '\n')
    print(f"\033[91m{reason}\033[0m\n")

    sys.exit(return_code)


def parse_args() -> Optional[str]:
    args = sys.argv[1:]
    argc = len(args)
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


# def setup_camera(cam: Camera):
#     with cam:
#         # Enable auto exposure time setting if camera supports it
#         try:
#             cam.ExposureAuto.set('Continuous')
#
#         except (AttributeError, VmbFeatureError):
#             pass
#
#         # Enable white balancing if camera supports it
#         try:
#             cam.BalanceWhiteAuto.set('Continuous')
#
#         except (AttributeError, VmbFeatureError):
#             pass
#
#         # Try to adjust GeV packet size. This Feature is only available for GigE - Cameras.
#         try:
#             stream = cam.get_streams()[0]
#             stream.GVSPAdjustPacketSize.run()
#             while not stream.GVSPAdjustPacketSize.is_done():
#                 pass
#
#         except (AttributeError, VmbFeatureError):
#             pass


# def setup_pixel_format(cam: Camera):
#     # Query available pixel formats. Prefer color formats over monochrome formats
#     cam_formats = cam.get_pixel_formats()
#     cam_color_formats = intersect_pixel_formats(cam_formats, COLOR_PIXEL_FORMATS)
#     convertible_color_formats = tuple(f for f in cam_color_formats
#                                       if opencv_display_format in f.get_convertible_formats())
#
#     cam_mono_formats = intersect_pixel_formats(cam_formats, MONO_PIXEL_FORMATS)
#     convertible_mono_formats = tuple(f for f in cam_mono_formats
#                                      if opencv_display_format in f.get_convertible_formats())
#
#     # if OpenCV compatible color format is supported directly, use that
#     if opencv_display_format in cam_formats:
#         cam.set_pixel_format(opencv_display_format)
#
#     # else if existing color format can be converted to OpenCV format do that
#     elif convertible_color_formats:
#         cam.set_pixel_format(convertible_color_formats[0])
#
#     # fall back to a mono format that can be converted
#     elif convertible_mono_formats:
#         cam.set_pixel_format(convertible_mono_formats[0])
#
#     else:
#         abort('Camera does not support an OpenCV compatible format. Abort.')


class ImageSaver(threading.Thread):
    def __init__(self, queue: Queue):
        super().__init__()
        self.queue = queue
        self.stop_event = threading.Event()

    def run(self):
        while not self.stop_event.is_set():
            try:
                image, filename = self.queue.get(timeout=1)
                # cv2.imwrite(filename, image)
            except:
                continue

    def stop(self):
        self.stop_event.set()


class Handler:
    def __init__(self, save_queue: Queue):
        self.display_queue  = Queue(60)
        self.save_queue     = save_queue
        self.prev_time      = time.time()   # FPS Calculating needs

    def get_image(self):
        return self.display_queue.get(True)

    def cal_FPS(self):
        ## For Calculating FPS per Frame
        current_time = time.time()
        elapsed_time = current_time - self.prev_time
        self.prev_time = current_time
        fps = 1 / elapsed_time
        return fps, elapsed_time


    def __call__(self, cam: Camera, stream: Stream, frame: Frame):
        if frame.get_status() == FrameStatus.Complete:
            # FIXME: The format is correct, no need to check
            # Convert frame if it is not already the correct format
            # if frame.get_pixel_format() == opencv_display_format:
            #     print("FRAME PIXEL IS OPENCV")
            #     display = frame
            # else:
            #     # This creates a copy of the frame. The original `frame` object can be requeued
            #     # safely while `display` is used
            #     print("\033[91mNeed to convert to OPENCV_PIXELFORMAT\033[0m")
            #     display = frame.convert_pixel_format(opencv_display_format)

            # Apply any real-time processing here (e.g., image filtering, detection)

            processed_image = frame.as_opencv_image()   # tested confirmed delay <0.005 ms

            fps, elapsed_time = self.cal_FPS()
            print(f'FPS: {fps:.2f} ({elapsed_time * 1000:.2f} ms) | {cam} acquired {frame}', flush=True)


            # Save the frame
            # filename = f'image_{self.frame_count:05}.jpg'
            # self.save_queue.put((processed_image, filename))

            # Display the frame
            self.display_queue.put(processed_image, True)

        cam.queue_frame(frame)


def main():
    cam_id = parse_args()

    with VmbSystem.get_instance():
        with get_camera(cam_id) as cam:
            # setup general camera settings and the pixel format in which frames are recorded

            save_queue = Queue()
            image_saver = ImageSaver(save_queue)
            image_saver.start()

            handler = Handler(save_queue)

            # Load camera settings from file.
            cam.load_settings('set/settings.xml', PersistType.All)
            print("--> Feature values have been loaded from given file '%s'" % 'set/settings.xml')

            try:
                # Start Streaming with a custom a buffer of 10 Frames (defaults to 5)
                cam.start_streaming(handler=handler, buffer_count=5)

                msg = 'Stream from \'{}\'. Press <Enter> to stop stream.'
                ENTER_KEY_CODE = 13
                while True:
                    key = cv2.waitKey(1)
                    if key == ENTER_KEY_CODE:
                        cv2.destroyWindow(msg.format(cam.get_name()))
                        break

                    # display = handler.get_image()
                    cv2.imshow(msg.format(cam.get_name()), handler.get_image())

            finally:
                cam.stop_streaming()
                image_saver.stop()
                image_saver.join()


if __name__ == '__main__':
    main()
