// Помощник окна Touch ID для слияния PR ядра (metis-0285). Собирает `pantheon setup` (swiftc), зовёт
// `pantheon merge run` из планового прохода (launchd, сессия владельца). Окно — системное (LocalAuthentication):
// роль его не нажмёт, ввод в него не подделать.
//   pantheon-touchid "<текст окна>" [секунд ожидания, по умолчанию 120]
// Код выхода: 0 — владелец подтвердил; 1 — отказ или «Не сливать»; 2 — окно не показать (нет Touch ID и пароля,
// не сессия владельца: LAError.notInteractive); 3 — ответа нет за время ожидания (окно закрыто); 64 — вызов не тот.
// В stderr — одна строка «код LAError: описание» для журнала, без текста окна.
import Foundation
import LocalAuthentication

let args = CommandLine.arguments
guard args.count >= 2, args.count <= 3, !args[1].isEmpty, args[1].count <= 400 else {
    FileHandle.standardError.write("вызов: pantheon-touchid \"<текст окна>\" [секунд]\n".data(using: .utf8)!)
    exit(64)
}
var wait = 120.0
if args.count == 3 {
    guard let w = Double(args[2]), w >= 1, w <= 3600 else { exit(64) }
    wait = w
}

func say(_ s: String) { FileHandle.standardError.write((s + "\n").data(using: .utf8)!) }

let ctx = LAContext()
ctx.localizedCancelTitle = "Не сливать"
// Touch ID, Apple Watch или пароль входа в Mac: всё это — сам владелец у своего Mac
let policy = LAPolicy.deviceOwnerAuthentication
var why: NSError?
guard ctx.canEvaluatePolicy(policy, error: &why) else {
    say("\(why?.code ?? 0): \(why?.localizedDescription ?? "окно недоступно")")
    exit(2)
}

let done = DispatchSemaphore(value: 0)
var code: Int32 = 1
ctx.evaluatePolicy(policy, localizedReason: args[1]) { ok, err in
    if ok {
        code = 0
    } else {
        let e = err as NSError?
        say("\(e?.code ?? 0): \(e?.localizedDescription ?? "отказ")")
        code = (e?.code == LAError.notInteractive.rawValue) ? 2 : 1
    }
    done.signal()
}
if done.wait(timeout: .now() + wait) == .timedOut {
    ctx.invalidate()  // закрыть окно: ответ позже времени ожидания не засчитывается
    say("время ожидания \(Int(wait)) с вышло")
    exit(3)
}
exit(code)
