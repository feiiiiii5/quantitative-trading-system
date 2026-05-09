fn main() -> Result<(), Box<dyn std::error::Error>> {
    let proto_dir = std::path::Path::new("../../proto");
    tonic_build::configure()
        .build_server(true)
        .build_client(true)
        .compile(
            &[
                proto_dir.join("order.proto"),
                proto_dir.join("common.proto"),
            ],
            &[proto_dir],
        )?;
    Ok(())
}
