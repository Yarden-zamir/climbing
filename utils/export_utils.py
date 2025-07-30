import base64
import datetime
import logging

logger = logging.getLogger("climbing_app")


def encode_redis_protocol(command_parts):
    """
    Encode a Redis command as Redis protocol format for binary data.
    Used for --pipe imports to handle binary data properly.
    """
    # Redis protocol format: *<number_of_arguments>\r\n$<length_of_argument>\r\n<argument>\r\n
    result_parts = [f"*{len(command_parts)}\r\n".encode()]
    
    for part in command_parts:
        if isinstance(part, bytes):
            # Binary data
            result_parts.append(f"${len(part)}\r\n".encode())
            result_parts.append(part)
            result_parts.append(b"\r\n")
        else:
            # Text data
            part_str = str(part)
            part_bytes = part_str.encode('utf-8')
            result_parts.append(f"${len(part_bytes)}\r\n".encode())
            result_parts.append(part_bytes)
            result_parts.append(b"\r\n")
    
    return b"".join(result_parts)


async def export_redis_database(redis_store) -> str:
    """
    Export Redis database using Redis protocol format for full compatibility.
    
    Exports both text data (DB 0) and binary images (DB 1) in Redis protocol format,
    ensuring that binary data is preserved exactly as-is during import.
    
    Usage:
        Export: curl -s http://localhost:8000/api/admin/export | jq -r '.export' > export.txt
        Import: cat export.txt | base64 -d | redis-cli --pipe
    
    Returns:
        Base64-encoded Redis protocol data for safe JSON transport
    """
    
    try:
        # Get keys from both text and binary Redis databases
        text_keys = redis_store.redis.keys("*")
        binary_keys = redis_store.binary_redis.keys("*")
        
        # Start building the export - pure Redis protocol data
        binary_protocol_parts = []
        export_count = 0
        
        # Helper function to escape Redis values
        def escape_redis_value(value):
            if isinstance(value, str):
                # Escape quotes and backslashes
                return value.replace('\\', '\\\\').replace('"', '\\"')
            return str(value)
        
        # Process text database keys (DB 0) - start with selecting DB 0
        binary_protocol_parts.append(encode_redis_protocol(["SELECT", "0"]))
        
        for key in text_keys:
            # Skip sensitive data
            if (key.startswith("session:") or 
                key.startswith("temp:")):
                continue
            
            try:
                # Get key type and TTL
                key_type = redis_store.redis.type(key)
                ttl = redis_store.redis.ttl(key)
                
                if key_type == "string":
                    value = redis_store.redis.get(key)
                    if value is not None:
                        binary_protocol_parts.append(encode_redis_protocol(["SET", key, value]))
                        if ttl > 0:
                            binary_protocol_parts.append(encode_redis_protocol(["EXPIRE", key, str(ttl)]))
                        export_count += 1
                        
                elif key_type == "hash":
                    hash_data = redis_store.redis.hgetall(key)
                    if hash_data:
                        hash_args = ["HSET", key]
                        for field, value in hash_data.items():
                            hash_args.extend([field, value])
                        binary_protocol_parts.append(encode_redis_protocol(hash_args))
                        if ttl > 0:
                            binary_protocol_parts.append(encode_redis_protocol(["EXPIRE", key, str(ttl)]))
                        export_count += 1
                        
                elif key_type == "set":
                    set_members = redis_store.redis.smembers(key)
                    if set_members:
                        set_args = ["SADD", key] + list(set_members)
                        binary_protocol_parts.append(encode_redis_protocol(set_args))
                        if ttl > 0:
                            binary_protocol_parts.append(encode_redis_protocol(["EXPIRE", key, str(ttl)]))
                        export_count += 1
                        
                elif key_type == "list":
                    list_values = redis_store.redis.lrange(key, 0, -1)
                    if list_values:
                        list_args = ["RPUSH", key] + list_values
                        binary_protocol_parts.append(encode_redis_protocol(list_args))
                        if ttl > 0:
                            binary_protocol_parts.append(encode_redis_protocol(["EXPIRE", key, str(ttl)]))
                        export_count += 1
                        
                elif key_type == "zset":
                    zset_data = redis_store.redis.zrange(key, 0, -1, withscores=True)
                    if zset_data:
                        zset_args = ["ZADD", key]
                        for member, score in zset_data:
                            zset_args.extend([str(score), member])
                        binary_protocol_parts.append(encode_redis_protocol(zset_args))
                        if ttl > 0:
                            binary_protocol_parts.append(encode_redis_protocol(["EXPIRE", key, str(ttl)]))
                        export_count += 1
                
            except Exception as e:
                logger.warning(f"Failed to export text key {key}: {e}")
                continue
        
        # Process binary database keys (DB 1) - switch to DB 1 for binary data
        binary_protocol_parts.append(encode_redis_protocol(["SELECT", "1"]))
        
        for key in binary_keys:
            # Convert bytes key to string for processing
            key_str = key.decode('utf-8') if isinstance(key, bytes) else key
            
            # Skip temp images
            if key_str.startswith("image:temp:"):
                continue
                
            try:
                # Get binary data and TTL
                binary_data = redis_store.binary_redis.get(key)
                ttl = redis_store.binary_redis.ttl(key)
                
                if binary_data is not None:
                    # Store as raw binary data using Redis protocol
                    binary_protocol_parts.append(encode_redis_protocol(["SET", key_str, binary_data]))
                    if ttl > 0:
                        binary_protocol_parts.append(encode_redis_protocol(["EXPIRE", key_str, str(ttl)]))
                    export_count += 1
                
            except Exception as e:
                logger.warning(f"Failed to export binary key {key_str}: {e}")
                continue
        
        # Combine all protocol parts - pure Redis protocol data
        protocol_data = b"".join(binary_protocol_parts)
        
        # Encode as base64 for safe JSON transport
        redis_export = base64.b64encode(protocol_data).decode('ascii')
        
        total_keys = len(text_keys) + len(binary_keys)
        logger.info(f"Redis export completed: {export_count} keys exported out of {total_keys} total keys (Text: {len(text_keys)}, Binary: {len(binary_keys)})")
        return redis_export
        
    except Exception as e:
        logger.error(f"Error during Redis export: {e}")
        raise 
