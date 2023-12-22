import os,sys
import base64, crcmod
import numpy as np
import cv2


DELIMITER = "-"
VALID_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567="+DELIMITER
DEBUG_IMAGE_PATH = "./temp/debug_images"
# Set parameters
rows = 12
cols = 20
box_size = 45
gap_size = 5

background_color = (255, 255, 255)  # RGB values for the white background

total_rows = rows * (box_size + gap_size) + gap_size
total_cols = cols * (box_size + gap_size) + gap_size

# Mapping from RGB to Base32

mapping = {
    "0,0,0"     : "A",
    "23,0,0"    : "B",
    "46,0,0"    : "C"
}


class Codec:

    def __init__(self):
        self.encode_map, self.decode_map, self.map_range = self.create_mapping(21, VALID_CHARS)
        self.debug_mode = False


    def encode(self, raw_data, local_seq=None, remote_seq=None):

        # base32_data = base64.b32encode((raw_data).encode("ascii")).decode("ascii")
        base32_data = base64.b32encode(raw_data).decode('utf-8')

        crc = self.__getCRC(base32_data)  

        line = (base32_data+DELIMITER+crc)
        grid = np.ones((total_rows, total_cols, 3), dtype=np.uint8)
        grid[0:total_rows, 0:total_cols, :] = background_color
        i = 0
        j = 0

        for c in line:
            grid[i:i + box_size, j:j + box_size, :] = self.encode_map[c]
    
            if i >= total_rows - box_size*2:
                i = 0
                j += box_size + gap_size
            else:
                i += box_size + gap_size

        return grid


    def decode(self, image, name=None):
        # Row 76 is the top
        image = image[78:total_rows+78,2:total_cols+2]
        # rows, cols, _ = image.shape

        # averages = []

        raw_data = ""

        offset = box_size+gap_size
        if self.debug_mode:
            cv2.imwrite(os.path.join(DEBUG_IMAGE_PATH, "debug_image.bmp"),image)
        for i in range(0, cols):
            for j in range(0, rows):
                box_name = str(i)+"_"+str(j)
                x1 = (i*offset)+2
                x2 = ((i+1)*offset)-(gap_size+2)
                y1 = (j*offset)+2
                y2 = ((j+1)*offset)-(gap_size+2)
                box = image[y1:y2, x1:x2]


                rgb = np.mean(box, axis=(0, 1))
                # Normalize the values so they match one of the possible values
                r = min(self.map_range, key=lambda x: abs(x - rgb[0]))
                g = min(self.map_range, key=lambda x: abs(x - rgb[1]))
                b = min(self.map_range, key=lambda x: abs(x - rgb[2]))
                if (r == 255 and g == 255 and b == 255) == False:
                    if self.debug_mode:
                        cv2.imwrite(os.path.join(DEBUG_IMAGE_PATH, box_name+"_debug_box.bmp"),box)
                    index = ("(%d, %d, %d)") % (r, g, b)
                    try:
                        raw_data+=(self.decode_map[index])
                    except KeyError:
                        cv2.imwrite(os.path.join(DEBUG_IMAGE_PATH, "debug_image.bmp"),image)
                        cv2.imwrite(os.path.join(DEBUG_IMAGE_PATH, "debug_box.bmp"),box)


        try:
            data, crc = raw_data.split(DELIMITER,1)
        except Exception as e:
            print("CRC Failed parsing: "+str(name))
            self.__write_debug_images(image,name)
            return (False, "".encode("utf-8"), (raw_data, image))


        if crc == self.__getCRC(data):
           # return (True, base64.b32decode(data).decode('utf-8'), (raw_data, image))
            return (True, base64.b32decode(data), (raw_data, image))
        else:
            print("CRC Failed: "+str(name))
            self.__write_debug_images(image,name)
            return (False, "".encode("utf-8"), (raw_data, image))


    # Unused, leaving it for now
    def __create_grid(self, rows, cols, box_size, gap_size):
        box_color = (0, 0, 0)  # RGB values for the black box
        background_color = (255, 255, 255)  # RGB values for the white background

        grid = np.ones((total_rows, total_cols, 3), dtype=np.uint8) * background_color  # Initialize with specified background color

    


        for i in range(0, total_rows, box_size + gap_size):
            r_value = 0
            for j in range(0, total_cols, box_size + gap_size):
                box_color = (r_value, 0, 0)
                grid[i:i + box_size, j:j + box_size, :] = box_color  # Set specified box color
                r_value = (r_value + 10) % 256

        return grid
        

    def __write_debug_images(self, image, name=None):
        offset = box_size+gap_size
        path = DEBUG_IMAGE_PATH
        if name:
            path = os.path.join(DEBUG_IMAGE_PATH,name.split(".")[0])
        if os.path.exists(path) == False:
            os.makedirs(path)
        cv2.imwrite(os.path.join(path, "debug_image.bmp"),image)
        for i in range(0, cols):
            for j in range(0, rows):
                name = str(i)+"_"+str(j)
                x1 = (i*offset)+2
                x2 = ((i+1)*offset)-(gap_size +2)
                y1 = (j*offset)+2
                y2 = ((j+1)*offset)-(gap_size +2)
                box = image[y1:y2, x1:x2]
                cv2.imwrite(os.path.join(path, name+"_debug_box.bmp"),box)


    # Create mapping
    def create_mapping(self, offset, chars):
        decode_map = {}
        encode_map = {}
        map_range = [255,0]
        rgb_values = []

        for r in range(offset,255,offset):
            rgb_values.append((r,0,0))
            map_range.append(r)
        for g in range(offset,255,offset):
            rgb_values.append((0,g,0))
        for b in range(offset,255,offset):
            rgb_values.append((0,0,b))
        
        if len(rgb_values) < len(chars):
            print("WARNING: Not enough RGB values to map characters to!")

        i = 0
        for c in chars:
            encode_map[c] = rgb_values[i]
            decode_map[str(encode_map[c])] = c
            i += 1

        return (encode_map, decode_map, map_range)


    def __getCRC(self, input_string):
        # Returns CRC value as Base32
        crc8 = crcmod.predefined.Crc('crc-8')
        crc8.update(input_string.encode('utf-8'))
        crc_bytes = crc8.crcValue.to_bytes(1, byteorder='big')
        base32_value = base64.b32encode(crc_bytes)
        return base32_value.decode()
    
    def debug(self, is_valid, msg_data, data, img, filename):

        # Temp for debugging
        org = (50, 200)
        font = cv2.FONT_HERSHEY_DUPLEX
        fontScale = 1
        color = (0, 0, 0)
        thickness = 2

        img = cv2.putText(img, str(data), org, font, fontScale, color, thickness)

        #cv2.imwrite(os.path.join(DEBUG_IMAGE_PATH,str(filename)+".bmp"),img)

    def enable_debug(self, value):
        self.debug_mode = value


# if __name__ == '__main__':
#     codec = Codec()
#     image = cv2.imread("../temp/out1.bmp")
#     is_valid, msg_data, data = codec.decode(image)
#     print(msg_data)
#     print(is_valid)

