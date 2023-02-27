import struct
import asyncio
import subprocess

from android.scrcpy.controller import Controller
from logzero import logger


class ClientDevice:
    @classmethod
    async def cancel_task(cls, task):
        # If task is already finish, this operation will return False, else return True(mean cancel operation success)
        task.cancel()
        try:
            # Wait task done, Exception inside the task will raise here
            await task
            # [task cancel operation no effect] 1.task already finished
        except asyncio.CancelledError:
            # [task cancel operation success] 2.catch task CancelledError Exception
            print("task is cancelled now")
        except Exception as e:
            # [task cancel operation no effect] 3.task already finished with a normal Exception
            print(f"task await exception {type(e)}, {e}")

    def __init__(self, device_id,
                 max_size=720,
                 bit_rate=1280000,
                 max_fps=30,
                 connect_timeout=300):
        self.device_id = device_id
        # scrcpy_server启动参数
        self.max_size = max_size
        self.bit_rate = bit_rate
        self.max_fps = max_fps
        # adb socket连接超时时间
        self.connect_timeout = connect_timeout
        # scrcpy连接
        self.deploy_shell_socket = None
        # 连接设备的socket, 监听设备socket的video_task任务
        self.video_socket = None
        self.control_socket = None
        self.video_task = None
        # 设备型号和分辨率
        self.device_name = None
        self.resolution = None
        # 设备并发锁
        self.device_lock = asyncio.Lock()
        # 设备控制器
        self.controller = Controller(self)
        # 需要推流得ws_client
        self.ws_client_list = list()

    async def prepare_server(self):
        commands2 = [
            "adb", "-s", self.device_id, "shell",
            "CLASSPATH=/data/local/tmp/scrcpy-server",
            "app_process",
            "/",
            "com.genymobile.scrcpy.Server",
            "1.24",  # Scrcpy server version
            f"log_level=info",  # Log level: info, verbose...
            f"max_size={self.max_size}",  # Max screen width (long side)
            f"bit_rate={self.bit_rate}",  # Bitrate of video
            f"max_fps={self.max_fps}",  # Max frame per second
            f"lock_video_orientation=-1",    # Lock screen orientation
            "tunnel_forward=true",  # Tunnel forward
            f"control=true",  # Control enabled
            f"display_id=0",  # Display id
            f"show_touches=true",  # Show touches
            f"stay_awake=false",  # scrcpy server Stay awake
            f"codec_options=profile=1,level=2",  # Codec (video encoding) options
            f"encoder_name=OMX.google.h264.encoder",  # Encoder name
            f"power_off_on_close=false",  # Power off screen after server closed
            "clipboard_autosync=false",  # auto sync clipboard
            f"downsize_on_error=true",   # when encode screen error downsize and retry encode screen
            "cleanup=true",     # enable cleanup thread
            f"power_on=true",   # power on when scrcpy deploy
            "send_device_meta=true",    # send device name, device resolution when video socket connect
            f"send_frame_meta=false",    # receive frame_meta,
            "send_dummy_byte=true",     # send dummy byte when video socket connect
            "raw_video_stream=false",  # video_socket just receive raw_video_stream
        ]
        self.deploy_shell_socket = subprocess.Popen(commands2, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        res = self.deploy_shell_socket.stdout.readlines(3)
        if len(res) == 1 and "Device" in res[0].decode():
            logger.info("[%s] start scrcpy success" % self.device_id)
        else:
            self.deploy_shell_socket = None
            for ws_client in self.ws_client_list:
                await ws_client.write_message("启动scrcpy服务失败")
                ws_client.close()
            raise ConnectionError("启动scrcpy服务失败")

    async def prepare_socket(self):
        # 1.video_socket
        self.video_socket = await self.create_socket('localabstract:scrcpy', timeout=self.connect_timeout)
        dummy_byte = await self.video_socket.read_exactly(1)
        if not len(dummy_byte) or dummy_byte != b"\x00":
            raise ConnectionError("not receive Dummy Byte")
        # 2.control_socket
        self.control_socket = await self.create_socket('localabstract:scrcpy', timeout=self.connect_timeout)
        # 3.device information
        self.device_name = (await self.video_socket.read_exactly(64)).decode("utf-8").rstrip("\x00")
        if not len(self.device_name):
            raise ConnectionError("not receive Device Name")
        self.resolution = struct.unpack(">HH", await self.video_socket.read_exactly(4))

    async def _video_task(self):
        while True:
            try:
                data = await self.video_socket.read_until(b'\x00\x00\x00\x01')
                current_nal_data = b'\x00\x00\x00\x01' + data.rstrip(b'\x00\x00\x00\x01')
                for ws_client in self.ws_client_list:
                    await ws_client.write_message(current_nal_data, True)
            except (asyncio.streams.IncompleteReadError, AttributeError):
                break

    async def start(self):
        await self.prepare_server()
        await self.prepare_socket()
        self.video_task = asyncio.create_task(self._video_task())

    async def stop(self):
        if self.video_socket:
            await self.video_socket.disconnect()
            self.video_socket = None
        if self.video_task:
            await self.cancel_task(self.video_task)
            self.video_task = None
        if self.control_socket:
            await self.control_socket.disconnect()
            self.control_socket = None
        if self.deploy_shell_socket:
            try:
                self.deploy_shell_socket.terminate()
            except:
                pass
            self.deploy_shell_socket = None

    async def create_socket(self, connect_name, timeout=300):
        socket = ClientSocket(self.device_id)
        for _ in range(timeout):
            try:
                await socket.connect()
                await socket.write(socket.cmd_format(f'host:transport:{self.device_id}'))
                assert await socket.read_exactly(4) == b'OKAY'
                await socket.write(socket.cmd_format(connect_name))
                assert await socket.read_exactly(4) == b'OKAY'
                return socket
            except:
                await socket.disconnect()
            await asyncio.sleep(0.01)
        else:
            raise ConnectionError(f"{self.device_id} create_connection to {connect_name} error!!")


class ClientSocket:
    """客户端连接"""
    @classmethod
    def cmd_format(cls, cmd):
        return "{:04x}{}".format(len(cmd), cmd).encode("utf-8")

    def __init__(self, device_id, socket_timeout=1):
        self.device_id = device_id
        self.socket_timeout = socket_timeout
        self.reader = None
        self.writer = None

    async def connect(self):
        try:
            self.reader, self.writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", "5037"), self.socket_timeout)
        except:
            await self.disconnect()

    async def read_exactly(self, cnt):
        return await self.reader.readexactly(cnt)

    async def read_until(self, sep):
        return await self.reader.readuntil(sep)

    async def write(self, data):
        self.writer.write(data)
        await self.writer.drain()

    async def disconnect(self):
        if self.writer:
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except ConnectionAbortedError:
                pass
            self.writer = self.reader = None

