//! Render the mjai-reviewer report template from an existing review JSON
//! (as produced by bigcoach / gokujan for model "RIGEL 1.4").
//!
//! The bigcoach review JSON is structurally identical to mjai-reviewer's
//! `--json` output (same `View` shape), so we can feed it straight into the
//! original tera templates and get byte-level identical page layout, replay
//! iframe, tile SVGs and probability tables -- no model re-run needed.
//!
//! Usage: render-report <in.json> <out.html> [lang]
//!   lang defaults to "zh".

use fluent_templates::static_loader;
use serde_json::Value;
use std::collections::HashMap;
use std::io::Read;

static_loader! {
    static LOCALES = {
        locales: "./locales",
        fallback_language: "en",
        customise: |bundle| bundle.set_use_isolating(false),
    };
}

fn kyoku_to_bakaze(args: &HashMap<String, Value>) -> tera::Result<Value> {
    const BAKAZE: &[&str] = &["East", "South", "West", "North"];
    let kyoku = args
        .get("kyoku")
        .and_then(|p| p.as_u64())
        .ok_or_else(|| tera::Error::msg("missing or invalid argument `kyoku`"))?
        as usize;
    Ok(BAKAZE[kyoku / 4].into())
}

fn kyoku_to_kyoku_in_bakaze(args: &HashMap<String, Value>) -> tera::Result<Value> {
    let kyoku = args
        .get("kyoku")
        .and_then(|p| p.as_u64())
        .ok_or_else(|| tera::Error::msg("missing or invalid argument `kyoku`"))?
        as usize;
    Ok((kyoku % 4 + 1).into())
}

fn pretty_round(args: &HashMap<String, Value>) -> tera::Result<Value> {
    let num = args
        .get("num")
        .and_then(|n| n.as_f64())
        .ok_or_else(|| tera::Error::msg("missing or invalid argument `num`"))?;
    let prec = args.get("prec").and_then(|p| p.as_u64()).unwrap_or(5);
    let split = args.get("split").and_then(|p| p.as_bool()).unwrap_or(false);
    let multiplier = 10_f64.powi(prec as i32);
    let num = (num * multiplier).round() / multiplier;
    let s = format!("{num:.0$}", prec as usize);
    if !split {
        return Ok(Value::String(s));
    }
    let seps = s.split('.').map(|s| Value::String(s.to_owned())).collect();
    Ok(Value::Array(seps))
}

fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 3 {
        eprintln!("usage: render-report <in.json> <out.html> [lang]");
        std::process::exit(2);
    }
    let mut buf = String::new();
    std::fs::File::open(&args[1])?.read_to_string(&mut buf)?;
    let mut v: Value = serde_json::from_str(&buf)?;

    // bigcoach payloads lack some fields the template touches; fill defaults.
    //  - details lack `q_value` (rendered by the template) -> 0.0
    //  - review.temperature may be null/absent (rendered via pretty_round) -> 0.1
    //  - review.model_tag is empty in bigcoach payloads; label the engine
    if let Some(rv) = v.get_mut("review").and_then(|x| x.as_object_mut()) {
        if !rv.get("temperature").and_then(|x| x.as_f64()).is_some() {
            rv.insert("temperature".into(), Value::from(0.1f64));
        }
        let tag = rv.get("model_tag").and_then(|x| x.as_str()).unwrap_or("");
        if tag.trim().is_empty() {
            rv.insert("model_tag".into(), Value::from("RIGEL 1.4"));
        }
    }
    if let Some(kyokus) = v
        .pointer_mut("/review/kyokus")
        .and_then(|x| x.as_array_mut())
    {
        for k in kyokus {
            if let Some(entries) = k.get_mut("entries").and_then(|x| x.as_array_mut()) {
                for e in entries {
                    if let Some(details) = e.get_mut("details").and_then(|x| x.as_array_mut()) {
                        for dd in details {
                            if let Some(obj) = dd.as_object_mut() {
                                obj.entry("q_value").or_insert(Value::from(0.0f64));
                            }
                        }
                    }
                }
            }
        }
    }

    let lang = args.get(3).map(String::as_str).unwrap_or("zh-TW");
    let lang_id = lang.parse()?;

    let mut tera = tera::Tera::default();
    tera.autoescape_on(vec![".tera", ".html"]);
    tera.register_function("kyoku_to_bakaze", kyoku_to_bakaze);
    tera.register_function("kyoku_to_kyoku_in_bakaze", kyoku_to_kyoku_in_bakaze);
    tera.register_function("pretty_round", pretty_round);
    tera.add_raw_templates([
        ("macros.tera", include_str!("../../mjai-reviewer-master/templates/macros.tera")),
        ("report.tera", include_str!("../../mjai-reviewer-master/templates/report.tera")),
        ("report.css", include_str!("../../mjai-reviewer-master/templates/report.css")),
        ("report.js", include_str!("../../mjai-reviewer-master/templates/report.js")),
        ("pai.svg", include_str!("../../mjai-reviewer-master/assets/pai.svg")),
    ])?;
    tera.register_function(
        "fluent",
        fluent_templates::FluentLoader::new(&*LOCALES).with_default_lang(lang_id),
    );

    let ctx = tera::Context::from_serialize(&v)?;
    let original = tera.render("report.tera", &ctx)?;

    let cfg = minify_html::Cfg {
        keep_comments: true,
        minify_css: true,
        minify_js: true,
        ..minify_html::Cfg::spec_compliant()
    };
    let out = minify_html::minify(original.as_bytes(), &cfg);
    std::fs::write(&args[2], &out)?;
    println!("ok {} -> {}", args[1], args[2]);
    Ok(())
}