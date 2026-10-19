"""Choose the SKU and the two catalog name sources; the second name is optional."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from mapper.features.csv_import import suggest_columns


class ColumnMappingDialog(tk.Toplevel):
    def __init__(self, parent, headers, *, catalog=False):
        super().__init__(parent)
        self.title('Choose CSV columns')
        self.resizable(False,False)
        self.result = None
        self.transient(parent)
        self.grab_set()
        self.headers = headers
        primary = 'Brand name (Honda)' if catalog else 'Full name (Vietnamese)'
        secondary = 'Full name (optional)' if catalog else 'Brand name (optional)'
        self.id_column = ttk.Combobox(self,values=headers,state='readonly',width=38)
        self.name_column = ttk.Combobox(self,values=headers,state='readonly',width=38)
        self.other_name_column = ttk.Combobox(self,values=['(none)']+headers,state='readonly',width=38)
        for row,(label,widget) in enumerate((('Product ID',self.id_column),(primary,self.name_column),(secondary,self.other_name_column))):
            ttk.Label(self,text=label).grid(row=row,column=0,padx=16,pady=8,sticky='w')
            widget.grid(row=row,column=1,padx=16,pady=8)
        id_index, name_index, other_index = suggest_columns(headers, catalog=catalog)
        self.id_column.current(id_index)
        self.name_column.current(name_index)
        self.other_name_column.current(other_index+1)
        buttons = ttk.Frame(self)
        buttons.grid(row=3,column=0,columnspan=2,padx=16,pady=16,sticky='e')
        ttk.Button(buttons,text='Cancel',command=self.destroy).pack(side='right',padx=8)
        ttk.Button(buttons,text='Import',command=self.confirm).pack(side='right')
        self.wait_visibility()
        self.focus_set()

    def confirm(self):
        pid,name,other = self.id_column.current(),self.name_column.current(),self.other_name_column.current()-1
        selected = [index for index in (pid,name,other) if index>=0]
        if min(pid,name)<0 or len(selected)!=len(set(selected)):
            messagebox.showerror('Choose columns','Choose different columns for the SKU and each name.',parent=self)
            return
        self.result = (pid,name,other)
        self.destroy()
