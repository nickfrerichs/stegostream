import os,sys
import base64, crcmod
import numpy as np
import cv2


DELIMITER = "-"
VALID_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567="+DELIMITER
DEBUG_IMAGE_PATH = "./temp/debug_images"

# Set parameters for the image and box sizes
width, height = 1280, 720
num_boxes_x = 58
num_boxes_y = 40
gap_size = 5
box_size_x = (width - (num_boxes_x - 1) * gap_size) // num_boxes_x
box_size_y = (height - (num_boxes_y - 1) * gap_size) // num_boxes_y

#box_size = min(box_size_x, box_size_y)

background_color = (255, 255, 255)  # RGB values for the white background

# Mapping from RGB to Base32

mapping = {
    "0,0,0"     : "A",
    "23,0,0"    : "B",
    "46,0,0"    : "C"
}


class Codec:

    def __init__(self):
        self.encode_map, self.decode_map, self.map_range = self.create_mapping(19, VALID_CHARS)
        self.debug_mode = False


    def encode(self, raw_data, local_seq=None, remote_seq=None):
        base32_data = base64.b32encode(raw_data).decode('utf-8')
        crc = self.__getCRC(base32_data)

        line = (base32_data + DELIMITER + crc)
        grid = np.ones((height, width, 3), dtype=np.uint8)
        grid[:num_boxes_y * (box_size_y + gap_size), :num_boxes_x * (box_size_x + gap_size), :] = background_color
        i = 0
        j = 0

        for c in line:

            # This fills up the current box
            grid[j:j + box_size_y, i:i + box_size_x, :] = self.encode_map[c]

            j += box_size_y + gap_size
            if j >= (num_boxes_y) * (box_size_y + gap_size):
                j = 0
                i += box_size_x + gap_size
                if i >= (num_boxes_x) * (box_size_x + gap_size):
                    i = 0

        return grid


    def decode(self, image, name=None):

        x_offset = box_size_x+gap_size
        y_offset = box_size_y+gap_size

        def get_raw_data_old():

            raw_data = ""
            count=0

            for i in range(0, num_boxes_x):
                for j in range(0, num_boxes_y):
                    count+=1
                    box_name = str(i)+"_"+str(j)
                    x1 = (i*x_offset)+2
                    x2 = ((i+1)*x_offset)-(gap_size+2)
                    y1 = (j*y_offset)+2
                    y2 = ((j+1)*y_offset)-(gap_size+2)
                    box = image[y1:y2, x1:x2]

                    rgb = np.mean(box, axis=(0, 1))
                    # Normalize the values so they match one of the possible values
                    r = min(self.map_range, key=lambda x: abs(x - rgb[0]))
                    g = min(self.map_range, key=lambda x: abs(x - rgb[1]))
                    b = min(self.map_range, key=lambda x: abs(x - rgb[2]))


                    # Exit if we encounter a white box, if this happens it's ether the end or something went wrong
                    if (r == 255 and g == 255 and b == 255):
                        return raw_data

                    # This is valid data, it is not white
                    if (r == 255 and g == 255 and b == 255) == False:
                        if self.debug_mode:
                            cv2.imwrite(os.path.join(DEBUG_IMAGE_PATH, box_name+"_debug_box.bmp"),box)
                        index = ("(%d, %d, %d)") % (r, g, b)
                        try:
                            raw_data+=(self.decode_map[index])
                        except KeyError:
                            cv2.imwrite(os.path.join(DEBUG_IMAGE_PATH, "debug_image.bmp"),image)
                            cv2.imwrite(os.path.join(DEBUG_IMAGE_PATH, "debug_box.bmp"),box)

            return raw_data
        
        def get_raw_data():
            # Set the dimensions of each box
            #box_size_x = 10  # Replace with your actual box size
            #box_size_y = 10  # Replace with your actual box size
            #gap_size = 2  # Replace with your actual gap size

            #num_boxes_x = (image.shape[1] - gap_size) // (box_size_x + gap_size)
            #num_boxes_y = (image.shape[0] - gap_size) // (box_size_y + gap_size)

            x_offset = box_size_x + gap_size
            y_offset = box_size_y + gap_size

            # Create an empty NumPy array to store the boxes
            boxes = np.empty((num_boxes_x * num_boxes_y, box_size_y, box_size_x, 3), dtype=np.uint8)

            # Populate the array with individual boxes
            count = 0
            for i in range(num_boxes_x):
                for j in range(num_boxes_y):
                    x1 = i * x_offset + 2
                    x2 = (i + 1) * x_offset - (gap_size + 2)
                    y1 = j * y_offset + 2
                    y2 = (j + 1) * y_offset - (gap_size + 2)

                    box = image[y1:y2, x1:x2]

                    # Ensure the box has the correct dimensions (crop if necessary)
                    box = cv2.resize(box, (box_size_x, box_size_y))

                    # Assign the box to the boxes array
                    boxes[count] = box

                    count += 1
            # Assume 'boxes' is a NumPy array of shape (num_boxes, height, width, 3)
            # where the last dimension represents RGB values

            # Calculate the mean RGB values for each box
            mean_rgb_values = np.mean(boxes, axis=(1, 2))

            # Find the closest values in self.map_range for each channel
            r_indices = np.argmin(np.abs(mean_rgb_values[:, 0, None] - np.array(self.map_range)[None, :]), axis=1)
            g_indices = np.argmin(np.abs(mean_rgb_values[:, 1, None] - np.array(self.map_range)[None, :]), axis=1)
            b_indices = np.argmin(np.abs(mean_rgb_values[:, 2, None] - np.array(self.map_range)[None, :]), axis=1)

            # Map the indices to the actual values
            r_values = np.array(self.map_range)[r_indices]
            g_values = np.array(self.map_range)[g_indices]
            b_values = np.array(self.map_range)[b_indices]

            # Reshape the values to be 2D arrays
            r_values_2d = r_values.reshape((num_boxes_x, num_boxes_y))
            g_values_2d = g_values.reshape((num_boxes_x, num_boxes_y))
            b_values_2d = b_values.reshape((num_boxes_x, num_boxes_y))

            raw_data = ""

            # Loop through each column
            for i in range(num_boxes_x):
                # Loop through each row in the column
                for j in range(num_boxes_y):
                    box_name = str(i)+"_"+str(j)
                    # Access the mapped values for the current box
                    r_value = r_values_2d[i, j]
                    g_value = g_values_2d[i, j]
                    b_value = b_values_2d[i, j]

                    # Exit if we encounter a white box, if this happens it's ether the end or something went wrong
                    if (r_value == 255 and g_value == 255 and b_value == 255):
                        return raw_data

                    # This is valid data, it is not white
                    if (r_value == 255 and g_value == 255 and b_value == 255) == False:
                        if self.debug_mode:
                            cv2.imwrite(os.path.join(DEBUG_IMAGE_PATH, box_name+"_debug_box.bmp"),box)
                        index = ("(%d, %d, %d)") % (r_value, g_value, b_value)
                        try:
                            raw_data+=(self.decode_map[index])
                        except KeyError:
                            cv2.imwrite(os.path.join(DEBUG_IMAGE_PATH, "debug_image.bmp"),image)
                            cv2.imwrite(os.path.join(DEBUG_IMAGE_PATH, "debug_box.bmp"),box)

            return raw_data

            

        raw_data = get_raw_data()


        if self.debug_mode:
            cv2.imwrite(os.path.join(DEBUG_IMAGE_PATH, "debug_image.bmp"),image)


        try:
            data, crc = raw_data.split(DELIMITER,1)
        except Exception as e:
            # log this instead? print("CRC Failed parsing: "+str(name))
            self.__write_debug_images(image,name)
            return (False, "".encode("utf-8"), (raw_data, image))


        if crc == self.__getCRC(data):
           # return (True, base64.b32decode(data).decode('utf-8'), (raw_data, image))
            return (True, base64.b32decode(data), (raw_data, image))
        else:
            # log this instead? print("CRC Failed: "+str(name))
            self.__write_debug_images(image,name)
            return (False, "".encode("utf-8"), (raw_data, image))

    
    # This is untested after switching to ffmpeg for streaming directly
    def __write_debug_images(self, image, name=None):
        x_offset = box_size_x+gap_size
        y_offset = box_size_y+gap_size
        path = DEBUG_IMAGE_PATH
        if name:
            path = os.path.join(DEBUG_IMAGE_PATH,name.split(".")[0])
        if os.path.exists(path) == False:
            os.makedirs(path)
        cv2.imwrite(os.path.join(path, "debug_image.bmp"),image)
        for i in range(0, width):
            for j in range(0, height):
                name = str(i)+"_"+str(j)
                x1 = (i*x_offset)+2
                x2 = ((i+1)*x_offset)-(gap_size +2)
                y1 = (j*y_offset)+2
                y2 = ((j+1)*y_offset)-(gap_size +2)
                box = image[y1:y2, x1:x2]
                if box.size > 0:
                    cv2.imwrite(os.path.join(path, name+"_debug_box.bmp"),box)


    # Create mapping
    def create_mapping(self, offset, chars):
        decode_map = {}
        encode_map = {}
        map_range = [255,0]
        rgb_values = []

        for r in range(offset,255-offset,offset):
            rgb_values.append((r,0,0))
            map_range.append(r)
        for g in range(offset,255-offset,offset):
            rgb_values.append((0,g,0))
        for b in range(offset,255-offset,offset):
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

    def enable_debug(self, value):
        self.debug_mode = value

# ## Debugging
# if __name__ == '__main__':
#     codec = Codec()
#     print (codec.map_range)
#     image_path = "./testimage.png"
#     text = "This is a test"
#     image = codec.encode(text.encode('utf-8'))
#     cv2.imwrite(image_path, image)
#     image = cv2.imread(image_path)
#     result, data, raw = codec.decode(image)
#     print(data)


