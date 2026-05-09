use std::collections::HashMap;

use crate::fix::parser::{
    parse, set_field, FixError, FixMessage,
    TAG_ACCOUNT, TAG_BEGIN_STRING, TAG_CLORD_ID, TAG_ENCRYPT_METHOD,
    TAG_HEART_BT_INT, TAG_MSG_SEQ_NUM, TAG_MSG_TYPE,
    TAG_ORDER_QTY, TAG_ORD_TYPE, TAG_ORIG_CLORD_ID, TAG_PRICE,
    TAG_RESET_SEQ_NUM_FLAG, TAG_SENDER_COMP_ID, TAG_SIDE,
    TAG_SYMBOL, TAG_TARGET_COMP_ID, TAG_TRANSACT_TIME,
};

const MSG_TYPE_LOGON: &str = "A";
const MSG_TYPE_LOGOUT: &str = "5";
const MSG_TYPE_HEARTBEAT: &str = "0";
const MSG_TYPE_TEST_REQUEST: &str = "1";
const MSG_TYPE_NEW_ORDER_SINGLE: &str = "D";
const MSG_TYPE_ORDER_CANCEL_REQUEST: &str = "F";
const MSG_TYPE_ORDER_CANCEL_REPLACE_REQUEST: &str = "G";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum FixSessionState {
    Disconnected,
    LoggingIn,
    Active,
    LogoutPending,
}

pub struct FixSession {
    pub sender_comp_id: String,
    pub target_comp_id: String,
    pub seq_num_out: i64,
    pub seq_num_in: i64,
    pub heartbeat_interval: u32,
    pub state: FixSessionState,
}

impl FixSession {
    pub fn new(
        sender_comp_id: String,
        target_comp_id: String,
        heartbeat_interval: u32,
    ) -> Self {
        Self {
            sender_comp_id,
            target_comp_id,
            seq_num_out: 1,
            seq_num_in: 0,
            heartbeat_interval,
            state: FixSessionState::Disconnected,
        }
    }

    fn next_seq_num(&mut self) -> i64 {
        let seq = self.seq_num_out;
        self.seq_num_out += 1;
        seq
    }

    fn build_message(&mut self, msg_type: &str, extra_fields: Vec<(i32, String)>) -> FixMessage {
        let seq = self.next_seq_num();
        let now = chrono::Utc::now().format("%Y%m%d-%H:%M:%S%.3f").to_string();

        let mut fields: HashMap<i32, String> = HashMap::new();
        fields.insert(TAG_MSG_TYPE, msg_type.to_string());
        fields.insert(TAG_SENDER_COMP_ID, self.sender_comp_id.clone());
        fields.insert(TAG_TARGET_COMP_ID, self.target_comp_id.clone());
        fields.insert(TAG_MSG_SEQ_NUM, seq.to_string());
        fields.insert(TAG_TRANSACT_TIME, now);

        for (tag, value) in extra_fields {
            fields.insert(tag, value);
        }

        let body_length = 0;
        let msg = FixMessage {
            begin_string: "FIX.4.4".to_string(),
            msg_type: msg_type.to_string(),
            sender_comp_id: self.sender_comp_id.clone(),
            target_comp_id: self.target_comp_id.clone(),
            msg_seq_num: seq,
            fields,
            checksum: 0,
            body_length,
        };

        let serialized = crate::fix::parser::serialize(&msg);
        match parse(&serialized) {
            Ok(parsed) => parsed,
            Err(_) => msg,
        }
    }

    pub fn logon(&mut self) -> FixMessage {
        self.state = FixSessionState::LoggingIn;
        self.build_message(
            MSG_TYPE_LOGON,
            vec![
                (TAG_ENCRYPT_METHOD, "0".to_string()),
                (TAG_HEART_BT_INT, self.heartbeat_interval.to_string()),
                (TAG_RESET_SEQ_NUM_FLAG, "Y".to_string()),
            ],
        )
    }

    pub fn logout(&mut self) -> FixMessage {
        self.state = FixSessionState::LogoutPending;
        self.build_message(MSG_TYPE_LOGOUT, vec![])
    }

    pub fn new_order_single(&mut self, order: &NewOrderParams) -> FixMessage {
        let side_str = match order.side {
            OrderSide::Buy => "1",
            OrderSide::Sell => "2",
        };
        let ord_type_str = match order.ord_type {
            OrdType::Market => "1",
            OrdType::Limit => "2",
            OrdType::Stop => "3",
            OrdType::StopLimit => "4",
        };
        let mut fields = vec![
            (TAG_CLORD_ID, order.cl_ord_id.clone()),
            (TAG_SYMBOL, order.symbol.clone()),
            (TAG_SIDE, side_str.to_string()),
            (TAG_ORDER_QTY, order.quantity.to_string()),
            (TAG_ORD_TYPE, ord_type_str.to_string()),
        ];
        if let Some(price) = order.price {
            fields.push((TAG_PRICE, price.to_string()));
        }
        if let Some(account) = &order.account {
            fields.push((TAG_ACCOUNT, account.clone()));
        }
        self.build_message(MSG_TYPE_NEW_ORDER_SINGLE, fields)
    }

    pub fn order_cancel_request(&mut self, cancel: &CancelParams) -> FixMessage {
        let side_str = match cancel.side {
            OrderSide::Buy => "1",
            OrderSide::Sell => "2",
        };
        self.build_message(
            MSG_TYPE_ORDER_CANCEL_REQUEST,
            vec![
                (TAG_CLORD_ID, cancel.cl_ord_id.clone()),
                (TAG_ORIG_CLORD_ID, cancel.orig_cl_ord_id.clone()),
                (TAG_SYMBOL, cancel.symbol.clone()),
                (TAG_SIDE, side_str.to_string()),
                (TAG_ORDER_QTY, cancel.quantity.to_string()),
            ],
        )
    }

    pub fn order_cancel_replace_request(&mut self, modify: &ModifyParams) -> FixMessage {
        let side_str = match modify.side {
            OrderSide::Buy => "1",
            OrderSide::Sell => "2",
        };
        let ord_type_str = match modify.ord_type {
            OrdType::Market => "1",
            OrdType::Limit => "2",
            OrdType::Stop => "3",
            OrdType::StopLimit => "4",
        };
        let mut fields = vec![
            (TAG_CLORD_ID, modify.cl_ord_id.clone()),
            (TAG_ORIG_CLORD_ID, modify.orig_cl_ord_id.clone()),
            (TAG_SYMBOL, modify.symbol.clone()),
            (TAG_SIDE, side_str.to_string()),
            (TAG_ORDER_QTY, modify.quantity.to_string()),
            (TAG_ORD_TYPE, ord_type_str.to_string()),
        ];
        if let Some(price) = modify.price {
            fields.push((TAG_PRICE, price.to_string()));
        }
        self.build_message(MSG_TYPE_ORDER_CANCEL_REPLACE_REQUEST, fields)
    }

    pub fn process_incoming(&mut self, msg: FixMessage) -> Result<Option<FixMessage>, FixError> {
        if !validate_checksum(&msg) {
            return Err(FixError::ChecksumMismatch {
                expected: msg.checksum,
                actual: calculate_checksum_from_msg(&msg),
            });
        }

        let incoming_seq = msg.msg_seq_num;
        if incoming_seq <= self.seq_num_in {
            tracing::warn!(
                incoming_seq = incoming_seq,
                expected_seq = self.seq_num_in + 1,
                "Duplicate or out-of-order sequence number"
            );
        }
        self.seq_num_in = std::cmp::max(self.seq_num_in, incoming_seq);

        match msg.msg_type.as_str() {
            MSG_TYPE_LOGON => {
                self.state = FixSessionState::Active;
                tracing::info!(
                    sender = %msg.sender_comp_id,
                    "FIX session logged on"
                );
                Ok(None)
            }
            MSG_TYPE_LOGOUT => {
                self.state = FixSessionState::Disconnected;
                tracing::info!("FIX session logged out");
                Ok(None)
            }
            MSG_TYPE_HEARTBEAT => Ok(None),
            MSG_TYPE_TEST_REQUEST => {
                let mut response = self.build_message(MSG_TYPE_HEARTBEAT, vec![]);
                if let Some(test_req_id) = msg.fields.get(&112) {
                    set_field(&mut response, 112, test_req_id.clone());
                }
                Ok(Some(response))
            }
            _ => Ok(None),
        }
    }

    pub fn heartbeat(&mut self) -> FixMessage {
        self.build_message(MSG_TYPE_HEARTBEAT, vec![])
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OrderSide {
    Buy,
    Sell,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OrdType {
    Market,
    Limit,
    Stop,
    StopLimit,
}

#[derive(Debug, Clone)]
pub struct NewOrderParams {
    pub cl_ord_id: String,
    pub symbol: String,
    pub side: OrderSide,
    pub quantity: i64,
    pub price: Option<f64>,
    pub ord_type: OrdType,
    pub account: Option<String>,
}

#[derive(Debug, Clone)]
pub struct CancelParams {
    pub cl_ord_id: String,
    pub orig_cl_ord_id: String,
    pub symbol: String,
    pub side: OrderSide,
    pub quantity: i64,
}

#[derive(Debug, Clone)]
pub struct ModifyParams {
    pub cl_ord_id: String,
    pub orig_cl_ord_id: String,
    pub symbol: String,
    pub side: OrderSide,
    pub quantity: i64,
    pub price: Option<f64>,
    pub ord_type: OrdType,
}

pub fn validate_checksum(msg: &FixMessage) -> bool {
    let serialized = crate::fix::parser::serialize(msg);
    let calculated = calculate_checksum(&serialized);
    calculated == msg.checksum
}

pub fn calculate_checksum(body: &str) -> u8 {
    let checksum_end = body
        .rfind('\u{0001}')
        .and_then(|pos| body[..pos].rfind('\u{0001}').map(|p| p + 1))
        .unwrap_or(0);
    body.as_bytes()[..checksum_end]
        .iter()
        .fold(0u8, |acc, &b| acc.wrapping_add(b))
}

fn calculate_checksum_from_msg(msg: &FixMessage) -> u8 {
    let serialized = crate::fix::parser::serialize(msg);
    calculate_checksum(&serialized)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_session() -> FixSession {
        FixSession::new("CLIENT".to_string(), "BROKER".to_string(), 30)
    }

    #[test]
    fn logon_message_structure() {
        let mut session = make_session();
        let msg = session.logon();
        assert_eq!(msg.msg_type, "A");
        assert_eq!(msg.sender_comp_id, "CLIENT");
        assert_eq!(msg.target_comp_id, "BROKER");
        assert_eq!(msg.msg_seq_num, 1);
        assert_eq!(msg.fields.get(&TAG_ENCRYPT_METHOD), Some(&"0".to_string()));
        assert_eq!(msg.fields.get(&TAG_HEART_BT_INT), Some(&"30".to_string()));
        assert_eq!(session.state, FixSessionState::LoggingIn);
    }

    #[test]
    fn logout_message_structure() {
        let mut session = make_session();
        let msg = session.logout();
        assert_eq!(msg.msg_type, "5");
        assert_eq!(session.state, FixSessionState::LogoutPending);
    }

    #[test]
    fn new_order_single_message() {
        let mut session = make_session();
        session.logon();
        let order = NewOrderParams {
            cl_ord_id: "ORD-001".to_string(),
            symbol: "600000.SH".to_string(),
            side: OrderSide::Buy,
            quantity: 1000,
            price: Some(10.50),
            ord_type: OrdType::Limit,
            account: Some("ACCT-1".to_string()),
        };
        let msg = session.new_order_single(&order);
        assert_eq!(msg.msg_type, "D");
        assert_eq!(msg.fields.get(&TAG_CLORD_ID), Some(&"ORD-001".to_string()));
        assert_eq!(msg.fields.get(&TAG_SYMBOL), Some(&"600000.SH".to_string()));
        assert_eq!(msg.fields.get(&TAG_SIDE), Some(&"1".to_string()));
        assert_eq!(msg.fields.get(&TAG_ORDER_QTY), Some(&"1000".to_string()));
        assert_eq!(msg.fields.get(&TAG_PRICE), Some(&"10.5".to_string()));
        assert_eq!(msg.fields.get(&TAG_ORD_TYPE), Some(&"2".to_string()));
        assert_eq!(msg.fields.get(&TAG_ACCOUNT), Some(&"ACCT-1".to_string()));
    }

    #[test]
    fn order_cancel_request_message() {
        let mut session = make_session();
        session.logon();
        let cancel = CancelParams {
            cl_ord_id: "CANCEL-001".to_string(),
            orig_cl_ord_id: "ORD-001".to_string(),
            symbol: "600000.SH".to_string(),
            side: OrderSide::Sell,
            quantity: 500,
        };
        let msg = session.order_cancel_request(&cancel);
        assert_eq!(msg.msg_type, "F");
        assert_eq!(msg.fields.get(&TAG_ORIG_CLORD_ID), Some(&"ORD-001".to_string()));
        assert_eq!(msg.fields.get(&TAG_SIDE), Some(&"2".to_string()));
    }

    #[test]
    fn order_cancel_replace_request_message() {
        let mut session = make_session();
        session.logon();
        let modify = ModifyParams {
            cl_ord_id: "MODIFY-001".to_string(),
            orig_cl_ord_id: "ORD-001".to_string(),
            symbol: "600000.SH".to_string(),
            side: OrderSide::Buy,
            quantity: 2000,
            price: Some(11.00),
            ord_type: OrdType::Limit,
        };
        let msg = session.order_cancel_replace_request(&modify);
        assert_eq!(msg.msg_type, "G");
        assert_eq!(msg.fields.get(&TAG_ORDER_QTY), Some(&"2000".to_string()));
        assert_eq!(msg.fields.get(&TAG_PRICE), Some(&"11.0".to_string()));
    }

    #[test]
    fn process_incoming_logon_activates_session() {
        let mut session = make_session();
        assert_eq!(session.state, FixSessionState::Disconnected);
        let mut logon_msg = session.logon();
        logon_msg.sender_comp_id = "BROKER".to_string();
        logon_msg.target_comp_id = "CLIENT".to_string();
        let result = session.process_incoming(logon_msg).expect("should succeed");
        assert!(result.is_none());
        assert_eq!(session.state, FixSessionState::Active);
    }

    #[test]
    fn process_incoming_test_request_generates_heartbeat() {
        let mut session = make_session();
        session.state = FixSessionState::Active;
        let mut test_req = session.build_message("1", vec![(112, "TEST123".to_string())]);
        test_req.sender_comp_id = "BROKER".to_string();
        test_req.target_comp_id = "CLIENT".to_string();
        let response = session
            .process_incoming(test_req)
            .expect("should succeed")
            .expect("should return heartbeat");
        assert_eq!(response.msg_type, "0");
        assert_eq!(response.fields.get(&112), Some(&"TEST123".to_string()));
    }

    #[test]
    fn process_incoming_logout_disconnects() {
        let mut session = make_session();
        session.state = FixSessionState::Active;
        let mut logout_msg = session.logout();
        logout_msg.sender_comp_id = "BROKER".to_string();
        logout_msg.target_comp_id = "CLIENT".to_string();
        let result = session.process_incoming(logout_msg).expect("should succeed");
        assert!(result.is_none());
        assert_eq!(session.state, FixSessionState::Disconnected);
    }

    #[test]
    fn seq_num_increments() {
        let mut session = make_session();
        assert_eq!(session.next_seq_num(), 1);
        assert_eq!(session.next_seq_num(), 2);
        assert_eq!(session.next_seq_num(), 3);
    }

    #[test]
    fn calculate_checksum_deterministic() {
        let mut session = make_session();
        let msg = session.logon();
        let serialized = crate::fix::parser::serialize(&msg);
        let c1 = calculate_checksum(&serialized);
        let c2 = calculate_checksum(&serialized);
        assert_eq!(c1, c2);
    }
}
