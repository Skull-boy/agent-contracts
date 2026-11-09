package main

import (
	"fmt"
	"net/http"
)

func main() {
	resp, err := http.Get("https://example.com/status")
	if err != nil {
		panic(err)
	}
	fmt.Println(resp.Status)
}
