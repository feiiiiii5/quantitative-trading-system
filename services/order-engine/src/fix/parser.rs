use std::collections::HashMap;

use serde::{Deserialize, Serialize};

pub const TAG_ACCOUNT: i32 = 1;
pub const TAG_ADV_ID: i32 = 2;
pub const TAG_CLORD_ID: i32 = 11;
pub const TAG_ORD_TYPE: i32 = 40;
pub const TAG_ORDER_QTY: i32 = 38;
pub const TAG_PRICE: i32 = 44;
pub const TAG_SIDE: i32 = 54;
pub const TAG_SYMBOL: i32 = 55;
pub const TAG_TIME_IN_FORCE: i32 = 59;
pub const TAG_TRANSACT_TIME: i32 = 60;
pub const TAG_ORIG_CLORD_ID: i32 = 41;
pub const TAG_ORDER_ID: i32 = 37;
pub const TAG_TEXT: i32 = 58;
pub const TAG_ENCRYPT_METHOD: i32 = 98;
pub const TAG_HEART_BT_INT: i32 = 108;
pub const TAG_RESET_SEQ_NUM_FLAG: i32 = 141;
pub const TAG_DEFAULT_CSTM_APPL_VER_ID: i32 = 1137;

pub const TAG_BEGIN_STRING: i32 = 8;
pub const TAG_BODY_LENGTH: i32 = 9;
pub const TAG_CHECKSUM: i32 = 10;
pub const TAG_MSG_SEQ_NUM: i32 = 34;
pub const TAG_MSG_TYPE: i32 = 35;
pub const TAG_SENDER_COMP_ID: i32 = 49;
pub const TAG_TARGET_COMP_ID: i32 = 56;
pub const TAG_SENDING_TIME: i32 = 52;

const SOH: char = '\u{0001}';

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize, thiserror::Error)]
pub enum FixError {
    #[error("FIX parse error: {0}")]
    ParseError(String),
    #[error("checksum mismatch: expected {expected:03}, got {actual:03}")]
    ChecksumMismatch { expected: u8, actual: u8 },
    #[error("missing required field: tag {0}")]
    MissingField(i32),
    #[error("invalid tag: {0}")]
    InvalidTag(i32),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FixMessage {
    pub begin_string: String,
    pub msg_type: String,
    pub sender_comp_id: String,
    pub target_comp_id: String,
    pub msg_seq_num: i64,
    pub fields: HashMap<i32, String>,
    pub checksum: u8,
    pub body_length: usize,
}

pub fn parse(raw: &str) -> Result<FixMessage, FixError> {
    let raw = raw.trim();
    if raw.is_empty() {
        return Err(FixError::ParseError("empty message".to_string()));
    }

    let mut fields: HashMap<i32, String> = HashMap::new();
    for pair in raw.split(SOH) {
        let pair = pair.trim();
        if pair.is_empty() {
            continue;
        }
        let (tag_str, value) = pair
            .split_once('=')
            .ok_or_else(|| FixError::ParseError(format!("malformed tag-value pair: {pair}")))?;
        let tag: i32 = tag_str
            .trim()
            .parse()
            .map_err(|_| FixError::InvalidTag(tag_str.trim().to_string().parse().unwrap_or(-1)))?;
        fields.insert(tag, value.to_string());
    }

    let begin_string = fields
        .get(&TAG_BEGIN_STRING)
        .cloned()
        .ok_or(FixError::MissingField(TAG_BEGIN_STRING))?;
    let msg_type = fields
        .get(&TAG_MSG_TYPE)
        .cloned()
        .ok_or(FixError::MissingField(TAG_MSG_TYPE))?;
    let sender_comp_id = fields
        .get(&TAG_SENDER_COMP_ID)
        .cloned()
        .ok_or(FixError::MissingField(TAG_SENDER_COMP_ID))?;
    let target_comp_id = fields
        .get(&TAG_TARGET_COMP_ID)
        .cloned()
        .ok_or(FixError::MissingField(TAG_TARGET_COMP_ID))?;
    let msg_seq_num: i64 = fields
        .get(&TAG_MSG_SEQ_NUM)
        .ok_or(FixError::MissingField(TAG_MSG_SEQ_NUM))?
        .parse()
        .map_err(|_| FixError::ParseError("invalid MsgSeqNum".to_string()))?;

    let checksum_str = fields
        .get(&TAG_CHECKSUM)
        .ok_or(FixError::MissingField(TAG_CHECKSUM))?;
    let checksum: u8 = checksum_str
        .parse()
        .map_err(|_| FixError::ParseError(format!("invalid checksum: {checksum_str}")))?;

    let body_length: usize = fields
        .get(&TAG_BODY_LENGTH)
        .ok_or(FixError::MissingField(TAG_BODY_LENGTH))?
        .parse()
        .map_err(|_| FixError::ParseError("invalid BodyLength".to_string()))?;

    let calculated = calculate_checksum_body(raw);
    if calculated != checksum {
        return Err(FixError::ChecksumMismatch {
            expected: checksum,
            actual: calculated,
        });
    }

    Ok(FixMessage {
        begin_string,
        msg_type,
        sender_comp_id,
        target_comp_id,
        msg_seq_num,
        fields,
        checksum,
        body_length,
    })
}

fn calculate_checksum_body(raw: &str) -> u8 {
    let checksum_end = raw
        .rfind(SOH)
        .map(|pos| {
            raw[..pos]
                .rfind(SOH)
                .map(|p| p + 1)
                .unwrap_or(0)
        })
        .unwrap_or(0);
    let bytes = raw.as_bytes();
    bytes[..checksum_end].iter().fold(0u8, |acc, &b| acc.wrapping_add(b))
}

pub fn serialize(msg: &FixMessage) -> String {
    let mut parts: Vec<String> = Vec::new();

    parts.push(format!("{}={}", TAG_BEGIN_STRING, msg.begin_string));

    let mut body_parts: Vec<String> = Vec::new();
    body_parts.push(format!("{}={}", TAG_MSG_TYPE, msg.msg_type));
    body_parts.push(format!("{}={}", TAG_SENDER_COMP_ID, msg.sender_comp_id));
    body_parts.push(format!("{}={}", TAG_TARGET_COMP_ID, msg.target_comp_id));
    body_parts.push(format!("{}={}", TAG_MSG_SEQ_NUM, msg.msg_seq_num));

    let mut other_tags: Vec<&i32> = msg
        .fields
        .keys()
        .filter(|t| !matches!(t, &&TAG_BEGIN_STRING | &&TAG_BODY_LENGTH | &&TAG_CHECKSUM | &&TAG_MSG_TYPE | &&TAG_SENDER_COMP_ID | &&TAG_TARGET_COMP_ID | &&TAG_MSG_SEQ_NUM))
        .collect();
    other_tags.sort();

    for tag in other_tags {
        if let Some(value) = msg.fields.get(tag) {
            body_parts.push(format!("{tag}={value}"));
        }
    }

    let body_content = body_parts.join(&SOH.to_string()) + &SOH.to_string();
    let body_length = body_content.len();

    parts.push(format!("{}={body_length}", TAG_BODY_LENGTH));
    parts.push(body_content);

    let full_body = parts.join(&SOH.to_string());
    let checksum = full_body
        .as_bytes()
        .iter()
        .fold(0u8, |acc, &b| acc.wrapping_add(b));
    parts.push(format!("{}={checksum:03}", TAG_CHECKSUM));

    parts.join(&SOH.to_string())
}

pub fn get_field(msg: &FixMessage, tag: i32) -> Option<&String> {
    msg.fields.get(&tag)
}

pub fn set_field(msg: &mut FixMessage, tag: i32, value: String) {
    msg.fields.insert(tag, value);
}

#[cfg(test)]
mod tests {
    use super::*;

    fn build_raw_fix(msg_type: &str, sender: &str, target: &str, seq: i64) -> String {
        let body = format!(
            "35={msg_type}\u{0001}49={sender}\u{0001}56={target}\u{0001}34={seq}\u{0001}"
        );
        let body_with_header = format!("8=FIX.4.4\u{0001}9={}\u{0001}{body}", body.len());
        let checksum = body_with_header
            .as_bytes()
            .iter()
            .fold(0u8, |acc, &b| acc.wrapping_add(b));
        format!("{body_with_header}10={checksum:03}\u{0001}")
    }

    #[test]
    fn parse_valid_logon_message() {
        let raw = build_raw_fix("A", "SENDER", "TARGET", 1);
        let msg = parse(&raw).expect("parse should succeed");
        assert_eq!(msg.msg_type, "A");
        assert_eq!(msg.sender_comp_id, "SENDER");
        assert_eq!(msg.target_comp_id, "TARGET");
        assert_eq!(msg.msg_seq_num, 1);
        assert_eq!(msg.begin_string, "FIX.4.4");
    }

    #[test]
    fn parse_empty_message_fails() {
        let result = parse("");
        assert!(matches!(result, Err(FixError::ParseError(_))));
    }

    #[test]
    fn parse_missing_required_field() {
        let raw = "8=FIX.4.4\u{0001}35=A\u{0001}10=000\u{0001}";
        let result = parse(raw);
        assert!(matches!(result, Err(FixError::MissingField(_))));
    }

    #[test]
    fn parse_malformed_pair() {
        let raw = "8=FIX.4.4\u{0001}NOEQUALSSIGN\u{0001}10=000\u{0001}";
        let result = parse(raw);
        assert!(matches!(result, Err(FixError::ParseError(_))));
    }

    #[test]
    fn serialize_roundtrip() {
        let raw = build_raw_fix("D", "SENDER", "TARGET", 42);
        let msg = parse(&raw).expect("parse should succeed");
        let serialized = serialize(&msg);
        let reparsed = parse(&serialized).expect("re-parse should succeed");
        assert_eq!(reparsed.msg_type, msg.msg_type);
        assert_eq!(reparsed.sender_comp_id, msg.sender_comp_id);
        assert_eq!(reparsed.target_comp_id, msg.target_comp_id);
        assert_eq!(reparsed.msg_seq_num, msg.msg_seq_num);
    }

    #[test]
    fn get_and_set_field() {
        let raw = build_raw_fix("D", "SENDER", "TARGET", 1);
        let mut msg = parse(&raw).expect("parse should succeed");
        assert!(get_field(&msg, TAG_SYMBOL).is_none());
        set_field(&mut msg, TAG_SYMBOL, "600000.SH".to_string());
        assert_eq!(get_field(&msg, TAG_SYMBOL), Some(&"600000.SH".to_string()));
    }

    #[test]
    fn checksum_mismatch_detected() {
        let raw = build_raw_fix("A", "S", "T", 1);
        let corrupted = raw.replace("10=", "10=999");
        let result = parse(&corrupted);
        assert!(matches!(result, Err(FixError::ChecksumMismatch { .. })));
    }

    #[test]
    fn parse_with_extra_fields() {
        let mut raw = build_raw_fix("D", "SENDER", "TARGET", 5);
        let insert_pos = raw.rfind("10=").unwrap();
        let extra = "55=600000.SH\u{0001}54=1\u{0001}38=1000\u{0001}44=10.50\u{0001}";
        let raw_with_extra = format!("{}{}{}", &raw[..insert_pos], extra, &raw[insert_pos..]);
        let msg = parse(&raw_with_extra).expect("parse should succeed");
        assert_eq!(get_field(&msg, TAG_SYMBOL), Some(&"600000.SH".to_string()));
        assert_eq!(get_field(&msg, TAG_SIDE), Some(&"1".to_string()));
        assert_eq!(get_field(&msg, TAG_ORDER_QTY), Some(&"1000".to_string()));
        assert_eq!(get_field(&msg, TAG_PRICE), Some(&"10.50".to_string()));
    }
}
