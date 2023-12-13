
import zlib, copy


class OutgoingTextMessage:
    def __init__(self, message_text, chunk_size):
        self.message_text = message_text
        self.chunk_size = chunk_size

        # Compress the message text
        self.compressed_data = zlib.compress(message_text.encode())

        # Initialize the index for iterating over chunks
        self.index = 0

        self.chunk_count = (len(self.compressed_data) + self.chunk_size - 1) // self.chunk_size

    def get_next_chunk(self):
        # Calculate the start and end indices for the current chunk
        start_index = self.index
        end_index = min(self.index + self.chunk_size, len(self.compressed_data))

        # Get the chunk of compressed data
        chunk_data = self.compressed_data[start_index:end_index]

        # Update the index for the next chunk
        self.index = end_index

        return chunk_data
    

class IncomingTextMessage:
    def __init__(self):
        # Initialize an empty list to store received compressed chunks
        self.received_chunks = []

    def receive_chunk(self, chunk):
        # Store the received compressed chunk
        self.received_chunks.append(chunk)

    def decompress_message(self):
        try:
            # Concatenate all received chunks
            concatenated_data = b"".join(self.received_chunks)

            # Decompress the concatenated data
            decompressed_message = zlib.decompress(concatenated_data)

            # Display the decompressed message as plaintext
            return(decompressed_message.decode())
        except zlib.error as e:
            # Handle zlib errors
            print(f"Error decompressing data: {e}")


