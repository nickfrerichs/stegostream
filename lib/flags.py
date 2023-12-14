# The assumption is that flags are always binary data outside of what is performed internally in this class


class Flags:
    NONE = 0
    SYN = 1
    ACK = 2
    SYN_ACK = 3
    START_DATA = 4
    END_DATA = 5   
    RESEND = 6  
    FLAG_F = 7  

    @staticmethod
    def get_bin(flags, flags_byte=None):

        if flags_byte is None:
            flags_byte = 0
        else:
            flags_byte = int.from_bytes(flags_byte, byteorder='big')            

        if isinstance(flags, int):
            flags = [flags]

        for flag in flags:
            if 1 <= flag <= 8:
                flags_byte |= 1 << (flag - 1)
        return flags_byte.to_bytes(1, byteorder='big')
    
    @staticmethod
    def get_int(flags):

        if isinstance(flags, int):
            flags = [flags]

        result_flags = 0
        for flag in flags:
            if 1 <= flag <= 8:
                result_flags |= 1 << (flag - 1)
        return result_flags

    @staticmethod
    def is_set(flags_byte, flags):
        
        if isinstance(flags_byte, bytes):
            flags_byte = int.from_bytes(flags_byte, byteorder='big')  
        
        if isinstance(flags, int):
            flags = [flags]

        for flag in flags:
            if 1 <= flag <= 8:
                if not bool(flags_byte & (1 << (flag - 1))):
                    return False
            else:
                print(f"Invalid flag value {flag}. Must be between 1 and 8.")
                return False
        return True

    @staticmethod
    def is_only_set(flags_byte, flag):

        if 1 <= flag <= 8:
            # Create a bitmask with only the specified flag set
            bitmask = 1 << (flag - 1)
            # Check if only the specified flag is set in flags_byte
            return int.from_bytes(flags_byte, byteorder='big') == bitmask





