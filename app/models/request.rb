class Request < ApplicationRecord
	belongs_to :user
	has_many :jobs, :dependent => :destroy
	has_many :excludes, :dependent => :destroy
	has_many :includes, :dependent => :destroy
	has_many :locations, :dependent => :destroy
end
