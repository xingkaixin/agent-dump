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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn decodes_every_frame_and_drops_a_torn_tail() {
        let frame = |text: &str| {
            ruzstd::encoding::compress_to_vec(
                text.as_bytes(),
                ruzstd::encoding::CompressionLevel::Fastest,
            )
        };
        let mut input = [frame("one\n"), frame("two\n")].concat();
        assert_eq!(
            frames(&input).unwrap(),
            (vec![b"one\n".to_vec(), b"two\n".to_vec()], false)
        );
        let third = frame("three\n");
        input.extend_from_slice(&third[..third.len() - 1]);
        assert_eq!(frames(&input).unwrap().0.len(), 2);
        assert!(frames(&input).unwrap().1);
        assert!(frames(b"not zstd").is_err());
    }
}
