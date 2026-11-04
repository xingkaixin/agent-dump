use std::io::Read;

pub fn compressed(path: &std::path::Path) -> bool {
    path.extension()
        .is_some_and(|extension| extension == "zst" || extension == "zstd")
}

/// Decodes concatenated frames. A frame cut off by the end of `input` is
/// still being written, so it is left out and reported as `torn`.
pub fn frames(mut input: &[u8]) -> crate::Result<(Vec<Vec<u8>>, bool)> {
    let mut frames = Vec::new();
    while !input.is_empty() {
        let mut frame = Vec::new();
        let decoded = ruzstd::decoding::StreamingDecoder::new(&mut input)
            .map_err(std::io::Error::other)
            .and_then(|mut decoder| decoder.read_to_end(&mut frame));
        match decoded {
            Ok(_) => frames.push(frame),
            Err(_) if input.is_empty() => return Ok((frames, true)),
            Err(error) => return Err(error.into()),
        }
    }
    Ok((frames, false))
}
