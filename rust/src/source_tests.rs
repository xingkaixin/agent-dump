use crate::diagnostics::Diagnostic;
use crate::provider::{Provider, source_roots};
use crate::provider_error::ProviderError;
use std::path::Path;

pub fn assert_missing(
    error: &(dyn std::error::Error + 'static),
    summary: &str,
    path: &Path,
    roots: &[String],
    step_hint: &str,
) {
    let error = error
        .downcast_ref::<ProviderError>()
        .expect("structured source failure");
    let ProviderError::Diagnostic {
        details,
        roots: actual_roots,
        capability,
        next_steps,
        ..
    } = error
    else {
        panic!("expected a source diagnostic");
    };
    assert_eq!(error.summary(false), summary);
    assert_eq!(details, &[format!("missing path: {}", path.display())]);
    assert_eq!(actual_roots, roots);
    assert!(capability.is_none());
    assert!(next_steps.iter().any(|step| step[0].contains(step_hint)));
    assert!(
        next_steps
            .iter()
            .all(|step| !step[1].is_empty() && step[0] != step[1])
    );
    for zh in [false, true] {
        let rendered =
            Diagnostic::read_failed(error, vec!["must not replace roots".into()], zh).render(zh);
        assert!(rendered.contains(summary));
        assert!(!rendered.contains("must not replace roots"));
        assert!(rendered.contains(if zh { "下一步:" } else { "Next steps:" }));
    }
}

pub fn removed_file(mut provider: impl Provider, path: &Path, id: &str, step_hint: &str) {
    let session = provider.find(id, &mut |_| Ok(())).unwrap().session.unwrap();
    assert_eq!(session.source_path, path);
    std::fs::remove_file(path).unwrap();
    let roots = source_roots(&provider);
    let error = provider
        .read(&session, false, &mut |_| Ok(()))
        .err()
        .unwrap();
    assert_missing(
        error.as_ref(),
        "session source file is missing",
        path,
        &roots,
        step_hint,
    );
    let error = provider.raw_export(&session).err().unwrap();
    assert_missing(
        error.as_ref(),
        "raw session source is missing",
        path,
        &roots,
        "original session file",
    );
    assert!(!path.exists());
    std::fs::create_dir(path).unwrap();
    let error = provider.raw_export(&session).err().unwrap();
    let rendered = Diagnostic::read_failed(error.as_ref(), Vec::new(), false).render(false);
    assert!(rendered.contains("raw export is not supported for this session source"));
    assert!(rendered.contains("session source is a directory, not a single raw file"));
    assert!(rendered.contains(&format!("source path: {}", path.display())));
    assert!(path.is_dir());
}
