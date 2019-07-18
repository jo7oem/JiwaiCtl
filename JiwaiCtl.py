import machines_controller.gauss_ctl as visa_gs

gauss = visa_gs.GaussMeter()

while True:

    cmd = input(">>>")
    if cmd in {"h", "help", "c", "cmd", "command"}:
        cmdlist()
    elif cmd in {"quit", "exit", "end"}:
        break
    elif cmd in {"ff"}:
        r = gauss.magnetic_field_fetch()
        print(r)
    elif cmd in {"query"}:
        query = input("####")
        gauss.set_query(query)
    else:
        print("""invaild command\nPlease type "h" or "help" """)
