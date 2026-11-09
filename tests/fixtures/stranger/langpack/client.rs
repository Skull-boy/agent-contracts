fn main() {
    let body = reqwest::blocking::get("https://example.com/status").unwrap();
    println!("{}", body.status());
}
