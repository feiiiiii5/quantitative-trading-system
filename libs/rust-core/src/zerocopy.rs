use bytes::Bytes;
use std::sync::Arc;

pub struct ZeroCopyBuffer {
    data: Bytes,
    offset: usize,
    len: usize,
}

impl ZeroCopyBuffer {
    pub fn from_bytes(data: Bytes) -> Self {
        let len = data.len();
        Self {
            data,
            offset: 0,
            len,
        }
    }

    pub fn from_vec(vec: Vec<u8>) -> Self {
        let len = vec.len();
        Self {
            data: Bytes::from(vec),
            offset: 0,
            len,
        }
    }

    pub fn slice(&self, start: usize, end: usize) -> Option<ZeroCopyBuffer> {
        if start > self.len || end > self.len || start > end {
            return None;
        }
        Some(ZeroCopyBuffer {
            data: self.data.slice(start..end),
            offset: 0,
            len: end - start,
        })
    }

    pub fn as_slice(&self) -> &[u8] {
        &self.data[self.offset..self.offset + self.len]
    }

    pub fn len(&self) -> usize {
        self.len
    }

    pub fn is_empty(&self) -> bool {
        self.len == 0
    }

    pub fn into_bytes(self) -> Bytes {
        self.data
    }

    pub fn share(&self) -> ZeroCopyBuffer {
        ZeroCopyBuffer {
            data: self.data.clone(),
            offset: self.offset,
            len: self.len,
        }
    }
}

pub struct BufferPool {
    pool: Arc<dashmap::DashMap<usize, Vec<Bytes>>>,
    max_buffers_per_size: usize,
}

impl BufferPool {
    pub fn new(max_buffers_per_size: usize) -> Self {
        Self {
            pool: Arc::new(dashmap::DashMap::new()),
            max_buffers_per_size,
        }
    }

    pub fn acquire(&self, size: usize) -> ZeroCopyBuffer {
        let mut entry = self.pool.entry(size).or_insert_with(Vec::new);
        if let Some(bytes) = entry.pop() {
            ZeroCopyBuffer::from_bytes(bytes)
        } else {
            ZeroCopyBuffer::from_vec(vec![0u8; size])
        }
    }

    pub fn release(&self, buffer: ZeroCopyBuffer) {
        let size = buffer.len();
        let bytes = buffer.into_bytes();
        let mut entry = self.pool.entry(size).or_insert_with(Vec::new);
        if entry.len() < self.max_buffers_per_size {
            entry.push(bytes);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_zero_copy_slice() {
        let buf = ZeroCopyBuffer::from_vec(vec![1, 2, 3, 4, 5]);
        let slice = buf.slice(1, 4).unwrap();
        assert_eq!(slice.as_slice(), &[2, 3, 4]);
    }

    #[test]
    fn test_zero_copy_share() {
        let buf = ZeroCopyBuffer::from_vec(vec![1, 2, 3]);
        let shared = buf.share();
        assert_eq!(buf.as_slice(), shared.as_slice());
    }

    #[test]
    fn test_buffer_pool() {
        let pool = BufferPool::new(10);
        let buf = pool.acquire(64);
        assert_eq!(buf.len(), 64);
        pool.release(buf);
        let buf2 = pool.acquire(64);
        assert_eq!(buf2.len(), 64);
    }
}
