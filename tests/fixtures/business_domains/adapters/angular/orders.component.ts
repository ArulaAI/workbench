import {Component} from '@angular/core';
import {HttpClient} from '@angular/common/http';

@Component({templateUrl: './orders.component.html'})
export class OrdersComponent {
  constructor(private http: HttpClient) {}
  save() { return this.http.post('/api/orders', {}); }
}
