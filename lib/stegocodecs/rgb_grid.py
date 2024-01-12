import os,sys
import base64, crcmod
import numpy as np
import cv2

DELIMITER = "-"
VALID_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567="+DELIMITER
DEBUG_IMAGE_PATH = "./temp/debug_images"

# Set parameters for the image and box sizes

class Codec:

    def __init__(self, msg, debug_mode=False, params=None):
        self.width, self.height = 1280, 720
        self.num_boxes_x = 40
        self.num_boxes_y = 35
        self.gap_size = 2

        if params:
            self.width = params["width"]
            self.height = params["height"]
            self.num_boxes_x = params["num_boxes_x"]
            self.num_boxes_y = params["num_boxes_y"]
            self.gap_size = params["gap_size"]

        self.box_size_x = (self.width - (self.num_boxes_x - 1) * self.gap_size) // self.num_boxes_x
        self.box_size_y = (self.height - (self.num_boxes_y - 1) * self.gap_size) //self.num_boxes_y

        if (params and params["box_reduction"] == False):
            self.box_reduction = 0
        else:
            self.box_reduction = int(self.box_size_y*.05)



        self.background_color = (255, 255, 255)  # RGB values for the white background

        self.encode_map, self.decode_map, self.map_range = self.create_mapping(50, VALID_CHARS)
        self.debug_mode = debug_mode
        self.msg = msg
        self.write_one_debug_image = True


    def encode(self, raw_data, local_seq=None, remote_seq=None):

        base32_data = base64.b32encode(raw_data).decode('utf-8')
        crc = self.__getCRC(base32_data)

        line = (base32_data + DELIMITER + crc)
        grid = np.ones((self.height, self.width, 3), dtype=np.uint8)
        grid[:self.num_boxes_y * (self.box_size_y + self.gap_size), :self.num_boxes_x * (self.box_size_x + self.gap_size), :] = self.background_color
        i = 0
        j = 0

        for c in line:

            # This fills up the current box
            grid[j:j + self.box_size_y, i:i + self.box_size_x, :] = self.encode_map[c]

            j += self.box_size_y + self.gap_size
            if j >= (self.num_boxes_y) * (self.box_size_y + self.gap_size):
                j = 0
                i += self.box_size_x + self.gap_size
                if i >= (self.num_boxes_x) * (self.box_size_x + self.gap_size):
                    i = 0

        return grid


    def decode(self, raw_image, name=None):

        image = cv2.resize(raw_image, (self.width, self.height))

        x_offset = self.box_size_x+self.gap_size
        y_offset = self.box_size_y+self.gap_size
        
        def get_raw_data():

            boxes = self.__get_decode_boxes(image)

            boxes_avg = self.__get_box_averages(boxes)
      
            boxes_mapped = self.__snap_to_map_range(boxes_avg)


            raw_data=""
            total_diff = 0
            total = 0

            for box in boxes_mapped:
                r_value,g_value,b_value, diff = box
                
                # Exit if we encounter a white box, if this happens it's ether the end or something went wrong
                if (r_value == 255 and g_value == 255 and b_value == 255):
                    return raw_data, total_diff/total
                total_diff += diff
                total +=1

                # This is a valid box, it is not white
                if (r_value == 255 and g_value == 255 and b_value == 255) == False:
                    index = ("(%d, %d, %d)") % (r_value, g_value, b_value)
                    try:
                        raw_data+=(self.decode_map[index])
                    except KeyError:
                        self.msg.print("CODEC: key error in decode_map")


            return raw_data, total_diff/total

            

        raw_data, diff = get_raw_data()


        if self.debug_mode:
            cv2.imwrite(os.path.join(DEBUG_IMAGE_PATH, "debug_image.bmp"),image)


        try:
            data, crc = raw_data.split(DELIMITER,1)
        except Exception as e:
            self.msg.print("CODEC: error parsing raw data "+str(name))
            # self.__write_debug_images(image,name)
            return (False, "".encode("utf-8"), (raw_data, image, diff))


        if crc == self.__getCRC(data):
            return (True, base64.b32decode(data), (raw_data, image, diff))
        else:
            self.msg.print("CODEC: CRC error "+str(name))
           # self.__write_debug_images(image,name)
            return (False, "".encode("utf-8"), (raw_data, image, diff))


    def get_debug_image(self, original_image, rgb_avg=None, rgb_map=None):

        def draw_text(text, x, y,):
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.3
            font_thickness = 1
            color = (0, 0, 0)
            cv2.putText(image, text, (x, y), font, font_scale, color, font_thickness, cv2.LINE_AA)


        def draw_text_rect(start, size):
            cv2.rectangle(image, (start[0], start[1]-int(size[1]*2)), (start[0] + size[0], start[1] + size[1]-5), (255, 255, 255), cv2.FILLED)



        image = original_image.copy()

        if rgb_avg is None:
            rgb_avg = self.__get_box_averages(self.__get_decode_boxes(original_image))
        if rgb_map is None:
            rgb_map = self.__snap_to_map_range(rgb_avg)

        count = 0
        for i in range(self.num_boxes_x):
            for j in range(self.num_boxes_y):
                # Calculate box coordinates
                x1 = i * (self.box_size_x + self.gap_size) + self.box_reduction
                y1 = j * (self.box_size_y + self.gap_size) + self.box_reduction
                x2 = x1 + self.box_size_x - 2 * self.box_reduction
                y2 = y1 + self.box_size_y - 2 * self.box_reduction

                # Draw rectangle on the original image
                cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)

                # Calculate text position for the first line (rgb_avg[count])
                text_x = x1 - self.box_reduction + 10
                text_y = y2 - 10  # Adjust this value for the vertical position of the text

                # Draw white background for both lines
                draw_text_rect((text_x, text_y),(80,10))
                try:
                    draw_text(f"({int(rgb_map[count][0])}, {int(rgb_map[count][1])}, {int(rgb_map[count][2])})", text_x+7, text_y)
                    text_y -= 10 
                    draw_text(f"({int(rgb_avg[count][0])}, {int(rgb_avg[count][1])}, {int(rgb_avg[count][2])})", text_x+7, text_y)
                except ValueError:
                    pass

                count += 1


        return image

    def get_debug_image_old(self, original_image):
        image = original_image.copy()

        for i in range(self.num_boxes_x):
            for j in range(self.num_boxes_y):
                # Calculate box coordinates
                x1 = i * (self.box_size_x + self.gap_size) + self.box_reduction
                y1 = j * (self.box_size_y + self.gap_size) + self.box_reduction
                x2 = x1 + self.box_size_x - 2 * self.box_reduction
                y2 = y1 + self.box_size_y - 2 * self.box_reduction

                # Draw rectangle on the original image
                cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)
        return image


    def __get_decode_boxes(self, image):
        #boxes = np.empty((num_boxes_x * num_boxes_y, box_size_y - 2 * box_reduction, box_size_x - 2 * box_reduction, 3), dtype=np.uint8)

        boxes = []

        x_coords = np.arange(0, self.num_boxes_x * (self.box_size_x + self.gap_size) - self.gap_size, self.box_size_x + self.gap_size)
        y_coords = np.arange(0, self.num_boxes_y * (self.box_size_y + self.gap_size) - self.gap_size, self.box_size_y + self.gap_size)

        for i, x in enumerate(x_coords):
            for j, y in enumerate(y_coords):
                x1, x2 = x + self.box_reduction, x + self.box_size_x - self.box_reduction
                y1, y2 = y + self.box_reduction, y + self.box_size_y - self.box_reduction

                boxes.append(image[y1:y2, x1:x2])

        return boxes

    def __get_box_averages(self, boxes):
        result_array = []

        for box in boxes:
            # Assuming 'boxes' is a NumPy array of shape (num_boxes, height, width, 3)
            # where the last dimension represents RGB values

            # Calculate the mean for each channel directly using NumPy
            r_avg = np.mean(box[:, :, 0])
            g_avg = np.mean(box[:, :, 1])
            b_avg = np.mean(box[:, :, 2])

            result_array.append((r_avg, g_avg, b_avg))

        return result_array
    
    def __snap_to_map_range(self, box_averages):

        result_array = []

        # Convert the value_range to a NumPy array for easier calculations
        value_range_np = np.array(self.map_range)

        for rgb in box_averages:
            diff = 0
            # Convert the RGB tuple to a NumPy array
            rgb_np = np.array(rgb)

            # Find the index of the closest value in the range for each channel
            r_index = np.argmin(np.abs(rgb_np[0] - value_range_np))
            g_index = np.argmin(np.abs(rgb_np[1] - value_range_np))
            b_index = np.argmin(np.abs(rgb_np[2] - value_range_np))

            # Calculate the absolute differences and sum them up
            diff = np.abs(rgb_np[0] - self.map_range[r_index]) + np.abs(rgb_np[1] - self.map_range[g_index]) + np.abs(rgb_np[2] - self.map_range[b_index])

            # Snap each value to the closest one in the range
            r_snap = value_range_np[r_index]
            g_snap = value_range_np[g_index]
            b_snap = value_range_np[b_index]

            result_array.append((r_snap, g_snap, b_snap, diff))

        return result_array

    

    # Create mapping
    def create_mapping(self, offset, chars):
        decode_map = {}
        encode_map = {}
        map_range = [255, 0]
        rgb_values = []

        for r in range(offset, 255 - offset, offset):
            map_range.append(r)
            for g in range(offset, 255 - offset, offset):
                for b in range(offset, 255 - offset, offset):
                    rgb_values.append((r, g, b))        
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
# class Blah:
#     def print(self, text):
#         print(text)


# if __name__ == '__main__':
#     msg = Blah()
#     codec = Codec(msg)
#     print(codec.decode_map)
#     for m, v in codec.decode_map.items():
#         print(m+" : "+v)


#     image = cv2.imread("")
#     valid, data, raw_data = codec.decode(image)
#     print(data)
#     print(raw_data[2])



