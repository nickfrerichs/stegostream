import os
import time
import random
import zlib

class BaseFile:

    def __init__(self, file_path):
        self.id = random.randint(0, 65535)
        self.path = file_path
        self.basename, self.ext = os.path.splitext(os.path.basename(file_path))
        self.name = self.basename+self.ext
        self.size = None
        if self.exists():
            self.size = self.__get_size()


    def exists(self):
        return os.path.exists(self.path)
    
    def __get_size(self):
        return os.path.getsize(self.path)
    

class OutgoingFile(BaseFile):

    def __init__(self, file_path):
        super().__init__(file_path)


    def get_file_chunks(self, chunk_size=25):
        start_flag = True

        segments = list(self.__get_file_segments())  # Store segments in a list

        for index, segment in enumerate(segments):
            compressed_segment = zlib.compress(segment)

            last_segment = index == len(segments) - 1

            for i in range(0, len(compressed_segment), chunk_size):
                chunk = compressed_segment[i:i + chunk_size]
                if start_flag and i == 0:
                    flag = 1  # Start of file and segment
                    start_flag = False
                elif i == 0:
                    flag = 2  # Start of segment
                elif i + chunk_size >= len(compressed_segment):
                    flag = 4 if last_segment else 3  # End of file and segment or end of segment
                else:
                    flag = 0  # Middle chunk within a segment

                yield (flag, chunk)

          

    def __get_file_segments(self):
        segment_size = int((100 * 1024))  # 100KB in bytes

        with open(self.path, 'rb') as file:
            while True:
                segment = file.read(segment_size)
                if not segment:
                    break
                yield segment


class IncomingFile(BaseFile):
    def __init__(self, file_path, file_id, timeout):
        super().__init__(file_path)
        self.id = file_id
        self.expire = time.time()+timeout
        self.compressed_chunk = None
        

    def process_incoming_chunk(self, data, flag):
        if flag == 1 or flag == 2:  # Start of a segment
            self.compressed_chunk = data
        elif flag == 3 or flag == 4:  # End of a segment
            self.compressed_chunk += data
            self.process_segment()
        elif flag == 0:  # Other chunks within a segment
            self.compressed_chunk += data

    def process_segment(self):
        # Decompress and write the segment to disk
        decompressed_segment = zlib.decompress(self.compressed_chunk)
        with open(self.path, 'ab') as file:
            file.write(decompressed_segment)
        # Reset compressed_chunk for the next segment
        self.compressed_chunk = None

