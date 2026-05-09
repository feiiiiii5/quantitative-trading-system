use std::alloc::{alloc, dealloc, Layout};
use std::ptr::NonNull;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use tracing::warn;

const DEFAULT_BLOCK_SIZE: usize = 4096;
const DEFAULT_MAX_BLOCKS: usize = 1024;

pub struct MemoryPool {
    block_size: usize,
    max_blocks: usize,
    allocated: AtomicUsize,
    in_use: AtomicUsize,
}

impl MemoryPool {
    pub fn new(block_size: usize, max_blocks: usize) -> Self {
        Self {
            block_size,
            max_blocks,
            allocated: AtomicUsize::new(0),
            in_use: AtomicUsize::new(0),
        }
    }

    pub fn with_defaults() -> Self {
        Self::new(DEFAULT_BLOCK_SIZE, DEFAULT_MAX_BLOCKS)
    }

    pub fn allocate(&self, size: usize) -> Option<PoolBlock> {
        let alloc_size = if size > self.block_size {
            size
        } else {
            self.block_size
        };

        let current = self.allocated.load(Ordering::Relaxed);
        if current >= self.max_blocks {
            warn!(
                "Memory pool exhausted: {}/{} blocks",
                current, self.max_blocks
            );
            return None;
        }

        let layout = Layout::from_size_align(alloc_size, 64).ok()?;
        let ptr = unsafe { alloc(layout) };
        let ptr = NonNull::new(ptr)?;

        self.allocated.fetch_add(1, Ordering::Relaxed);
        self.in_use.fetch_add(1, Ordering::Relaxed);

        Some(PoolBlock {
            ptr,
            size: alloc_size,
            layout,
            pool: Arc::new(MemoryPoolHandle {
                allocated: &self.allocated,
                in_use: &self.in_use,
            }),
        })
    }

    pub fn stats(&self) -> (usize, usize) {
        (
            self.allocated.load(Ordering::Relaxed),
            self.in_use.load(Ordering::Relaxed),
        )
    }
}

struct MemoryPoolHandle {
    allocated: *const AtomicUsize,
    in_use: *const AtomicUsize,
}

unsafe impl Send for MemoryPoolHandle {}
unsafe impl Sync for MemoryPoolHandle {}

impl Drop for MemoryPoolHandle {
    fn drop(&mut self) {
        unsafe {
            (*self.in_use).fetch_sub(1, Ordering::Relaxed);
        }
    }
}

pub struct PoolBlock {
    ptr: NonNull<u8>,
    size: usize,
    layout: Layout,
    pool: Arc<MemoryPoolHandle>,
}

unsafe impl Send for PoolBlock {}

impl PoolBlock {
    pub fn as_slice(&self) -> &[u8] {
        unsafe { std::slice::from_raw_parts(self.ptr.as_ptr(), self.size) }
    }

    pub fn as_mut_slice(&mut self) -> &mut [u8] {
        unsafe { std::slice::from_raw_parts_mut(self.ptr.as_ptr(), self.size) }
    }

    pub fn size(&self) -> usize {
        self.size
    }
}

impl Drop for PoolBlock {
    fn drop(&mut self) {
        unsafe {
            dealloc(self.ptr.as_ptr(), self.layout);
            (*self.pool.allocated).fetch_sub(1, Ordering::Relaxed);
        }
    }
}

unsafe impl Sync for MemoryPool {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_allocate_and_drop() {
        let pool = MemoryPool::new(4096, 10);
        {
            let block = pool.allocate(100).unwrap();
            assert!(block.size() >= 100);
            assert_eq!(pool.stats(), (1, 1));
        }
        assert_eq!(pool.stats(), (0, 0));
    }

    #[test]
    fn test_pool_exhaustion() {
        let pool = MemoryPool::new(4096, 2);
        let _b1 = pool.allocate(100).unwrap();
        let _b2 = pool.allocate(100).unwrap();
        assert!(pool.allocate(100).is_none());
    }

    #[test]
    fn test_large_allocation() {
        let pool = MemoryPool::new(4096, 10);
        let block = pool.allocate(8192).unwrap();
        assert_eq!(block.size(), 8192);
    }
}
