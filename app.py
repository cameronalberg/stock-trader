import os

from cs50 import SQL
from flask import Flask, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True


# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")

# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")


@app.route("/")
@login_required
def index():

    # Find all unique stocks that have been purchased by user and current balance
    holdings = db.execute("SELECT DISTINCT symbol from transactions WHERE userID = ?", session["user_id"])
    balance = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])[0].get("cash")
    assets = balance
    active_holdings = []

    # Generate list of all holdings
    for holding in holdings:
        holding["shares"] = db.execute("SELECT SUM(shares) FROM transactions WHERE userID = ? AND symbol = ?",
                                       session["user_id"], holding.get("symbol"))[0].get("SUM(shares)")

        # Lookup current information of stock to get name and latest share price
        result = lookup(holding.get("symbol"))
        price = result.get("price")
        total = price * holding["shares"]

        # Assign stock data to element of list
        holding["price"] = usd(price)
        holding["name"] = result.get("name")
        holding["total"] = usd(total)

        # Add total value of given stock to assets
        assets += total

        # Only add holdings with non-zero shares to list displayed to user
        if holding["shares"] != 0:
            active_holdings.append(holding)

    # Add element containing users current balance to end of list
    active_holdings.append({'symbol': 'CASH', 'total': usd(balance)})
    return render_template("index.html", holdings=active_holdings, assets=usd(assets))


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():

    # On POST, check for valid submission. If valid, add transaction to database and update users balance
    if request.method == "POST":
        try:
            shares = float(request.form.get("shares"))
        except ValueError:
            return apology("input must be numeric", 400)

        # Check if number of shares is an integer
        if shares.is_integer() is False:
            return apology("number of shares must be a positive integer", 400)

        # Check if number of shares is positive
        elif shares < 1:
            return apology("number of shares must be greater than 0", 400)

        # Get latest data from provided symbol
        result = lookup(request.form.get("symbol"))

        # Check if symbol is valid
        if result is not None:
            stock_price = result.get("price")
            symbol = result.get("symbol")

            # Update balance to reflect purchase
            balance = db.execute("SELECT cash FROM users WHERE id = ?",
                                 session["user_id"])[0].get("cash")
            balance -= (stock_price * shares)

            # Check that balance is not negative after potential transaction
            if balance < 0:
                return apology("not enough cash to complete purchase")

            # Update balance and add transaction into database
            db.execute("UPDATE users SET cash = ? WHERE id = ?", balance, session["user_id"])
            db.execute("INSERT INTO transactions (userID, shares, symbol, price) VALUES (?, ?, ?, ?)",
                       session["user_id"], shares, symbol, stock_price)

            return redirect("/")

        # If symbol is not valid, return error
        return apology("invalid symbol")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("buy.html")


@app.route("/history")
@login_required
def history():

    # Get all transactions executed by user
    transactions = db.execute("SELECT * from transactions WHERE userID = ?", session["user_id"])
    return render_template("history.html", transactions=transactions)


@app.route("/profile")
@login_required
def profile():

    # Display username and balance of current user
    username = db.execute("SELECT username FROM users WHERE id = ?", session["user_id"])[0].get("username")
    balance = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])[0].get("cash")
    return render_template("profile.html", username=username, balance=usd(balance))


@app.route("/password", methods=["GET", "POST"])
@login_required
def password():

    # On POST, check if current password and new password meet requirements. If valid, update password and logout user.
    if request.method == "POST":

        # Check that current password is provided
        if not request.form.get("current_password"):
            return apology("must provide current password", 403)

        # Get actual current password (hashed) from database
        current_password = db.execute("SELECT hash FROM users WHERE id = ?", session["user_id"])[0]["hash"]

        # Check password entered to password provided
        if not check_password_hash(current_password, request.form.get("current_password")):
            return apology("current password is incorrect", 403)

        # Check that new password fields are entered correctly
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        elif request.form.get("password") != request.form.get("confirmation"):
            return apology("passwords do not match", 403)

        # Generate hash of new password
        new_password_hashed = generate_password_hash(request.form.get("password"))

        # Update users password
        db.execute("UPDATE users SET hash = ? WHERE id = ?", new_password_hashed, session["user_id"])

        # Log user out
        return redirect("/logout")

    else:
        return render_template("password.html")


@app.route("/addcash", methods=["GET", "POST"])
@login_required
def addcash():

    # On POST, check if value entered is valid. If valid, add to current user's balance.
    if request.method == "POST":
        addedcash = int(request.form.get("addedcash"))

        # Check that value entered is positive
        if addedcash <= 0:
            return apology("value must be greater than 0")

        # Get current balance and add cash
        balance = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])[0].get("cash")
        balance += addedcash

        # Update balance in database
        db.execute("UPDATE users SET cash = ? WHERE id = ?", balance, session["user_id"])
        return redirect("/")

    else:
        return render_template("addcash.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = ?", request.form.get("username"))

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():

    if request.method == "POST":
        symbol = request.form.get("symbol")
        result = lookup(symbol)

        if result is not None:

            name = result.get("name")
            price = usd(result.get("price"))
            return render_template("quoted.html", name=name, price=price, symbol=symbol)

        return apology("invalid symbol")

    # If GET request, display quote page
    else:
        return render_template("quote.html")


@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        # Check that username field is not empty
        if not request.form.get("username"):
            return apology("must provide username", 400)

        # Check database for username
        username = request.form.get("username")
        rows = db.execute("SELECT * FROM users WHERE username = ?", username)

        # Check that username does not already exist
        if len(rows) != 0:
            return apology("username already taken", 400)

        # Check that password field is not empty and that both password fields match
        elif not request.form.get("password"):
            return apology("must provide password", 400)

        elif request.form.get("password") != request.form.get("confirmation"):
            return apology("passwords do not match", 400)

        # Hash password and add username and hashed password to database
        password_hashed = generate_password_hash(request.form.get("password"))
        db.execute("INSERT INTO users (username, hash) VALUES (?, ?)", username, password_hashed)
        return redirect("/")

    # If GET request, display registration page
    else:
        return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():

    if request.method == "POST":

        # Get value of shares from input field as integer
        shares = int(request.form.get("shares"))

        # Check that shares is greater than 1
        if shares < 1:
            return apology("must select 1 or more shares")

        # Look up stock based on provided symbol
        result = lookup(request.form.get("symbol"))

        # Check that symbol is valid
        if result is not None:

            symbol = result.get("symbol")

            # Get sum of all available shares of stock in users portfolio
            current_shares = db.execute("SELECT SUM(shares) FROM transactions WHERE userID = ? AND symbol = ?",
                                        session["user_id"], symbol)[0].get("SUM(shares)")

            # If no shares exist or shares request to sell exceeds available shares, return error
            if current_shares is None or (current_shares < shares):
                return apology("not enough shares to sell")

            stock_price = result.get("price")

            # Calculate new user balance based on shares being sold
            balance = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])[0].get("cash")
            balance += (stock_price * shares)

            # Set shares value to negative to represent shares sold
            shares *= -1

            # Update available balance with new balance
            db.execute("UPDATE users SET cash = ? WHERE id = ?", balance, session["user_id"])

            # Add transaction to database
            db.execute("INSERT INTO transactions (userID, shares, symbol, price) VALUES (?, ?, ?, ?)",
                       session["user_id"], shares, symbol, stock_price)
            return redirect("/")

        # If symbol not found, return error
        return apology("invalid symbol")

    # If GET request, display sell page
    else:
        # Generate list of all holdings
        holdings = db.execute("SELECT DISTINCT symbol from transactions WHERE userID = ?", session["user_id"])

        return render_template("sell.html", holdings=holdings)


def errorhandler(e):
    """Handle error"""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return apology(e.name, e.code)


# Listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)
