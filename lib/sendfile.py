import os
import time
import random
import zlib

class BaseFile:

    def __init__(self, file_path):
        self.id = random.randint(0, 65535)
        self.path = file_path
        self.name, self.ext = os.path.splitext(os.path.basename(file_path))
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


    def get_file_chunks(self, chunk_size=20):
        for segment in self.__get_file_segments():
            compressed_segment = zlib.compress(segment.encode())

            for i in range(0, len(compressed_segment), chunk_size):
                chunk = compressed_segment[i:i + chunk_size]
                if i == 0:
                    yield (1, chunk)  # Start of a segment
                elif i + chunk_size >= len(compressed_segment):
                    yield (2, chunk)  # End of a segment
                else:
                    yield (0, chunk)  # Other chunks within a segment
          


    def __get_file_segments(self):
        segment_size = 100 * 1024  # 100KB in bytes

        with open(self.path, 'rb') as file:
            while True:
                segment = file.read(segment_size)
                if not segment:
                    break
                yield segment


    # I think ChatGPT added this to be cute. It can probably go away
    # def read_file_in_chunks(file_path, chunk_size=1024):
    #     with open(file_path, 'rb') as file:
    #         while True:
    #             chunk = file.read(chunk_size)
    #             if not chunk:
    #                 break  # End of file
    #             yield chunk


class IncomingFile(BaseFile):
    def __init__(self, file_path, file_id, timeout):
        super().__init__(file_path)
        self.id = file_id
        self.expire = time.time()+timeout
        self.compressed_chunk = None
        

    def process_incoming_chunk(self, data, flag):
    
        if flag == 1:  # Start of a segment
            self.compressed_chunk = data
        elif flag == 2:  # End of a segment
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





