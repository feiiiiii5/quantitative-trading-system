use crossbeam_channel::{Receiver, Sender, bounded};
use std::sync::atomic::{AtomicBool, Ordering};

pub struct SPSCQueue<T> {
    tx: Sender<T>,
    rx: Receiver<T>,
    closed: AtomicBool,
}

impl<T> SPSCQueue<T> {
    pub fn new(capacity: usize) -> Self {
        let (tx, rx) = bounded(capacity);
        Self {
            tx,
            rx,
            closed: AtomicBool::new(false),
        }
    }

    pub fn push(&self, item: T) -> Result<(), T> {
        if self.closed.load(Ordering::Acquire) {
            return Err(item);
        }
        self.tx.try_send(item).map_err(|e| e.into_inner())
    }

    pub fn pop(&self) -> Option<T> {
        self.rx.try_recv().ok()
    }

    pub fn len(&self) -> usize {
        self.rx.len()
    }

    pub fn is_empty(&self) -> bool {
        self.rx.is_empty()
    }

    pub fn close(&self) {
        self.closed.store(true, Ordering::Release);
    }

    pub fn is_closed(&self) -> bool {
        self.closed.load(Ordering::Acquire)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_push_pop() {
        let q = SPSCQueue::new(10);
        q.push(42u64).unwrap();
        q.push(43u64).unwrap();
        assert_eq!(q.pop(), Some(42));
        assert_eq!(q.pop(), Some(43));
        assert_eq!(q.pop(), None);
    }

    #[test]
    fn test_capacity_limit() {
        let q = SPSCQueue::new(2);
        q.push(1u64).unwrap();
        q.push(2u64).unwrap();
        assert!(q.push(3u64).is_err());
    }

    #[test]
    fn test_close() {
        let q = SPSCQueue::<u64>::new(10);
        q.close();
        assert!(q.push(1u64).is_err());
        assert!(q.is_closed());
    }
}
