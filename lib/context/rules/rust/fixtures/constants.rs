const MAX_RETRIES: u32 = 3;
const API_BASE_URL: &str = "https://api.example.com";
static DEFAULT_TIMEOUT_MS: u64 = 30000;
static mut MUTABLE_GLOBAL: i32 = 0;

struct MyStruct {
    name: String,
    value: i32,
}

enum Color {
    Red,
    Green,
    Blue,
}

trait MyTrait {
    fn do_thing(&self);
}

impl MyStruct {
    fn new(name: String) -> Self {
        MyStruct { name, value: 0 }
    }
}

impl MyTrait for MyStruct {
    fn do_thing(&self) {
        println!("{}", self.name);
    }
}

fn do_stuff(n: i32) -> i32 {
    let local = n + 1;
    local
}

type AliasType = Vec<String>;

macro_rules! my_macro {
    ($x:expr) => { $x + 1 };
}
