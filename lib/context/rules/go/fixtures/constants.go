package main

const MaxRetries = 3

const (
	APIBaseURL       = "https://api.example.com"
	DefaultTimeoutMS = 30000
)

func doStuff() int {
	return MaxRetries
}

type MyStruct struct {
	Name string
}

func (m *MyStruct) Method() string {
	return m.Name
}
